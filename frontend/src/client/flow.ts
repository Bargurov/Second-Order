// One analysis page as a pure state machine: what the server last said about the analysis, the quote the person may
// approve, whether they approved it, what is in flight and the last notice. React calls `reduce`; nothing here sends,
// times out or retries. Every rule below is about what the page offers, never a substitute for the server's checks.
import type { Account, Analysis, Quote } from "../contracts/user.ts";
import type { Notice } from "./refusals.ts";

export type Busy = null | "reading" | "quoting" | "running";

export interface FlowState {
  analysis: Analysis | null;
  /** The active quote, issued by the server for exactly this analysis and Effort, that the person may approve. */
  quote: Quote | null;
  /** The person's approval of `quote`. Never set by the page, cleared by any change. */
  approved: boolean;
  busy: Busy;
  notice: Notice | null;
  /** The last run reply was a repeat of an approval already used: nothing was charged or sent again. */
  repeat: boolean;
  /** A run's reply did not arrive or could not be read, so whether it was sent is unknown. No quote, approval or run
   * is offered until a read of this analysis from the server succeeds. A failed read keeps this. */
  uncertain: boolean;
}

export type FlowEvent =
  /** A successful read of the analysis from the server (or the analysis a confirmed reply carried). */
  | { type: "read"; analysis: Analysis }
  | { type: "busy"; busy: Busy }
  | { type: "quoted"; quote: Quote }
  | { type: "approve"; checked: boolean }
  | { type: "ran"; analysis: Analysis; duplicate: boolean }
  /** A run whose reply is unconfirmed (lost, unreadable or a server error): it may or may not have been sent. */
  | { type: "run-unconfirmed"; notice: Notice }
  /** Any other refusal or unconfirmed reply, including a failed read or quote: it changes no gate. */
  | { type: "notice"; notice: Notice }
  | { type: "dismiss" };

export const initialFlow: FlowState = { analysis: null, quote: null, approved: false, busy: null, notice: null,
                                        repeat: false, uncertain: false };

/** Whether a quote may be approved for this analysis: active, and issued for this exact analysis and Effort. */
export function quoteFits(quote: Quote | null, analysis: Analysis | null): quote is Quote {
  return quote !== null && analysis !== null && analysis.state === "prepared" && quote.state === "active" &&
    quote.analysis_id === analysis.analysis_id && quote.effort === analysis.effort;
}

/** The one rule for sending a run: no uncertain run outstanding, nothing in flight, and the person's approval of a quote
 * that fits the analysis as last read. The page's Run control and the controller both use it. */
export function mayRun(state: FlowState): state is FlowState & { analysis: Analysis; quote: Quote } {
  return !state.uncertain && state.busy === null && state.approved && quoteFits(state.quote, state.analysis);
}

export function reduce(state: FlowState, event: FlowEvent): FlowState {
  switch (event.type) {
    case "read": {
      const same = state.analysis?.analysis_id === event.analysis.analysis_id;
      const base = same ? state : { ...initialFlow };
      // The server's latest quote for a prepared analysis, if it is still active; otherwise none.
      const quote = quoteFits(event.analysis.quote, event.analysis) ? event.analysis.quote : null;
      // An approval survives a re-read only of the same active quote, and never across an uncertain run.
      const keep = same && !state.uncertain && quote !== null && state.quote?.quote_id === quote.quote_id;
      return { ...base, analysis: event.analysis, quote, approved: keep && state.approved, busy: null,
               repeat: same && state.repeat, uncertain: false };
    }
    case "busy":
      return { ...state, busy: event.busy, notice: event.busy ? null : state.notice };
    case "quoted":
      if (state.uncertain || !quoteFits(event.quote, state.analysis)) return { ...state, busy: null };
      return { ...state, quote: event.quote, approved: false, busy: null, notice: null, repeat: false };
    case "approve":
      return { ...state, approved: event.checked && !state.uncertain && quoteFits(state.quote, state.analysis) &&
                                   state.busy === null };
    case "ran":
      return { ...state, analysis: event.analysis, quote: null, approved: false, busy: null, notice: null,
               repeat: event.duplicate, uncertain: false };
    case "run-unconfirmed":
      return { ...state, notice: event.notice, busy: null, approved: false, quote: null, repeat: false, uncertain: true };
    case "notice": {
      const dropQuote = event.notice.next === "new_quote" || event.notice.next === "choose_effort";
      return { ...state, notice: event.notice, busy: null, approved: false, quote: dropQuote ? null : state.quote };
    }
    case "dismiss":
      return { ...state, notice: null };
  }
}

export type Panel =
  | { kind: "loading" }
  | { kind: "uncertain" }
  | { kind: "quote"; previous: Quote | null; canQuote: boolean }
  | { kind: "approve"; quote: Quote; canRun: boolean }
  | { kind: "running" }
  | { kind: "recorded" }
  | { kind: "held"; state: "failed" | "unresolved" }
  | { kind: "not_sent" };

/** What the analysis page offers now. Run is offered only when `mayRun` holds; after an unconfirmed run, only reading
 * the analysis again is offered. */
export function panel(state: FlowState): Panel {
  const analysis = state.analysis;
  if (!analysis) return { kind: "loading" };
  if (state.uncertain) return { kind: "uncertain" };
  switch (analysis.state) {
    case "prepared":
      return quoteFits(state.quote, analysis)
        ? { kind: "approve", quote: state.quote, canRun: mayRun(state) }
        : { kind: "quote", previous: analysis.quote, canQuote: state.busy === null };
    case "running":
      return { kind: "running" };
    case "recorded":
      return { kind: "recorded" };
    case "failed":
    case "unresolved":
      return { kind: "held", state: analysis.state };
    case "not_sent":
      return { kind: "not_sent" };
  }
}

/** Where keyboard focus goes after an explicit action changes what the page offers: the new quote to read and approve,
 * the recorded result, or the state card for any other new state (held, unsent, running, uncertain, a fresh quote to
 * ask for). Null: nothing new to go to, so focus stays where it is. */
export type FocusTarget = "quote" | "result" | "state";

export function focusAfter(before: Panel, after: Panel): FocusTarget | null {
  if (after.kind === "approve") {
    return before.kind === "approve" && before.quote.quote_id === after.quote.quote_id ? null : "quote";
  }
  if (after.kind === before.kind || after.kind === "loading") return null;
  return after.kind === "recorded" ? "result" : "state";
}

/** The allowance belongs beside the decision it informs (asking for or approving a quote, a run in flight or uncertain);
 * once the analysis is recorded, held or unsent there is no decision left, so it follows the result. */
export function allowanceBesideDecision(after: Panel): boolean {
  return after.kind === "quote" || after.kind === "approve" || after.kind === "running" || after.kind === "uncertain" ||
    after.kind === "loading";
}

/** Server-reported reasons a quote or run will likely be refused, shown beside the action, never used to block it:
 * the server decides at quote and run time. */
export function advisories(account: Account | null, quote: Quote | null): string[] {
  if (!account) return [];
  const lines: string[] = [];
  if (!account.analysis.available) lines.push(account.analysis.detail);
  if (account.daily.remaining === 0) lines.push("The server reports no analyses left today; a run will be refused until the day resets.");
  if (quote && account.credits.available < quote.credits) {
    lines.push(`The server reports ${account.credits.available} credits available, fewer than this quote's ${quote.credits}.`);
  }
  return lines;
}
