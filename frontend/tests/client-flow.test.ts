// The Client's analysis flow (src/client/flow.ts) against the SYNTHETIC user-contract fixtures: what the page offers
// in each server state, when an approval exists, what clears it, and what the header says meanwhile. These are page
// rules only; the server's own checks (quotes, credits, daily limits) are proved by the combined integration gate, not
// here.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { Account, Analysis, Quote } from "../src/contracts/user.ts";
import {
  advisories, allowanceBesideDecision, focusAfter, initialFlow, mayRun, panel, quoteFits, reduce, type FlowEvent,
  type FlowState,
} from "../src/client/flow.ts";
import { headerState } from "../src/client/present.ts";
import { noticeFor } from "../src/client/refusals.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const analysisOf = (name: string) => load<{ analysis: Analysis }>(`user-contract-${name}`).analysis;
const errors = load<Record<string, { contract: "user-api-0.1"; code: string; detail: string }>>("user-contract-errors");
const prepared = analysisOf("analysis-prepared");
const quoted = analysisOf("analysis-quoted");
const quote = load<{ quote: Quote }>("user-contract-quote").quote;
const recorded = load<{ analysis: Analysis; duplicate: boolean }>("user-contract-run-recorded");
const account = load<Account>("user-contract-account");
const readerB = load<Account>("client-account-reader-b");
const run = (events: FlowEvent[], from: FlowState = initialFlow) => events.reduce(reduce, from);
const refused = (code: string) => noticeFor({ state: "refused", status: 409, error: errors[code] as never });

test("a prepared analysis offers a quote; reading it prepares, quotes and runs nothing", () => {
  const state = run([{ type: "read", analysis: prepared }]);
  assert.deepEqual(panel(state), { kind: "quote", previous: null, canQuote: true });
  assert.equal(state.approved, false);
  assert.deepEqual(panel(initialFlow), { kind: "loading" });
});

test("a server quote for exactly this analysis and Effort is offered, never pre-approved", () => {
  const state = run([{ type: "read", analysis: prepared }, { type: "quoted", quote }]);
  assert.equal(panel(state).kind, "approve");
  assert.equal(state.approved, false);
  assert.deepEqual(panel(state), { kind: "approve", quote, canRun: false });
  const approved = reduce(state, { type: "approve", checked: true });
  assert.deepEqual(panel(approved), { kind: "approve", quote, canRun: true });
  const sending = reduce(approved, { type: "busy", busy: "running" });
  assert.deepEqual(panel(sending), { kind: "approve", quote, canRun: false });  // One action in flight at a time.
});

test("a quote for another analysis or Effort, or one that is not active, is never offered", () => {
  const otherEffort = { ...quote, effort: "low" as const };
  const otherAnalysis = { ...quote, analysis_id: `${quote.analysis_id}.other` };
  const expired = { ...quote, state: "expired" as const };
  for (const wrong of [otherEffort, otherAnalysis, expired]) {
    const state = run([{ type: "read", analysis: prepared }, { type: "quoted", quote: wrong }]);
    assert.equal(state.quote, null);
    assert.equal(panel(state).kind, "quote");
    assert.equal(quoteFits(wrong, prepared), false);
  }
});

test("the server's own quote on a prepared analysis is offered when active, with its expiry left to the server", () => {
  const state = run([{ type: "read", analysis: quoted }]);
  assert.equal(panel(state).kind, "approve");
  // The page never compares the quote's expiry with this machine's clock: an old expiry is still offered, and the
  // server's refusal (quote_expired) is what ends it.
  const old = { ...quoted, quote: { ...quoted.quote!, expires_at: "2000-01-01T00:00:00+00:00" } };
  assert.equal(panel(run([{ type: "read", analysis: old }])).kind, "approve");
});

test("choosing another Effort (another analysis) drops the quote and the approval", () => {
  const approved = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true }]);
  assert.equal(approved.approved, true);
  const low = { ...prepared, analysis_id: prepared.analysis_id.replace(/\.high$/, ".low"), effort: "low" as const };
  const moved = reduce(approved, { type: "read", analysis: low });
  assert.equal(moved.quote, null);
  assert.equal(moved.approved, false);
  assert.equal(panel(moved).kind, "quote");
});

test("a re-read that shows the quote expired, used or superseded clears it and the approval", () => {
  const approved = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true }]);
  for (const state of ["expired", "used", "superseded"] as const) {
    const after = reduce(approved, { type: "read", analysis: { ...quoted, quote: { ...quoted.quote!, state } } });
    assert.equal(after.quote, null, state);
    assert.equal(after.approved, false, state);
    assert.deepEqual(panel(after), { kind: "quote", previous: { ...quoted.quote!, state }, canQuote: true });
  }
  const same = reduce(approved, { type: "read", analysis: quoted });
  assert.equal(same.approved, true);  // The same active quote, read again: the approval stands.
});

test("every refusal clears the approval; an expired or superseded quote and an unsupported Effort drop the quote", () => {
  const approved = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true }]);
  for (const code of ["quote_expired", "quote_superseded", "unsupported_effort"]) {
    const after = reduce(approved, { type: "notice", notice: refused(code) });
    assert.equal(after.approved, false, code);
    assert.equal(after.quote, null, code);
  }
  for (const code of ["insufficient_credits", "daily_limit_reached", "quote_mismatch", "already_attempted"]) {
    const after = reduce(approved, { type: "notice", notice: refused(code) });
    assert.equal(after.approved, false, code);
    assert.equal(panel(after).kind, "approve", code);  // The quote is kept; approving it again is a new decision.
  }
  const unconfirmed = reduce(approved, { type: "notice", notice: noticeFor({ state: "unconfirmed", status: 503,
                                                                             message: "No reply.", error: null }) });
  assert.equal(unconfirmed.approved, false);
});

test("a run reply ends the quote; a repeat is flagged; held and finished states offer no run", () => {
  const approved = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true }]);
  const ran = reduce(approved, { type: "ran", analysis: recorded.analysis, duplicate: false });
  assert.deepEqual([ran.quote, ran.approved, ran.repeat, panel(ran).kind], [null, false, false, "recorded"]);
  const repeat = reduce(approved, { type: "ran", analysis: recorded.analysis, duplicate: true });
  assert.equal(repeat.repeat, true);
  const kinds = Object.fromEntries(["analysis-running", "analysis-failed", "analysis-unresolved", "analysis-not-sent"]
    .map((name) => [name, panel(run([{ type: "read", analysis: analysisOf(name) }])).kind]));
  assert.deepEqual(kinds, { "analysis-running": "running", "analysis-failed": "held", "analysis-unresolved": "held",
                            "analysis-not-sent": "not_sent" });
  for (const name of ["analysis-running", "analysis-unresolved", "analysis-recorded"]) {
    const state = run([{ type: "read", analysis: analysisOf(name) }, { type: "approve", checked: true }]);
    assert.equal(state.approved, false, name);
  }
});

const lostReply = noticeFor({ state: "unconfirmed", status: null, message: "No reply arrived from the server.", error: null });

test("an unconfirmed run gates the page: approving again cannot make Run available before a read", () => {
  // The reproduction from the targeted review: quoted, approved, running, then an unconfirmed run reply.
  const running = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true },
                       { type: "busy", busy: "running" }]);
  const uncertain = reduce(running, { type: "run-unconfirmed", notice: lostReply });
  assert.deepEqual(panel(uncertain), { kind: "uncertain" });
  const reapproved = reduce(uncertain, { type: "approve", checked: true });
  assert.equal(reapproved.approved, false);
  assert.equal(mayRun(reapproved), false);
  assert.deepEqual(panel(reapproved), { kind: "uncertain" });
  const requoted = reduce(reapproved, { type: "quoted", quote: quoted.quote! });  // A quote reply cannot lift it either.
  assert.deepEqual([requoted.quote, panel(requoted).kind], [null, "uncertain"]);
});

test("each layer of the gate holds on its own, even with a fitting quote or a stale approval present", () => {
  const uncertain = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true },
                         { type: "run-unconfirmed", notice: lostReply }]);
  const withQuote = { ...uncertain, quote: quoted.quote! };  // States the reducer never builds; the rules still hold.
  assert.equal(reduce(withQuote, { type: "approve", checked: true }).approved, false);
  const stale = { ...withQuote, approved: true };
  assert.equal(mayRun(stale), false);
  assert.deepEqual(panel(stale), { kind: "uncertain" });
  // A read of the same analysis under the same active quote lifts the gate but never revives that approval.
  assert.equal(reduce(stale, { type: "read", analysis: quoted }).approved, false);
});

test("a failed or unreadable read keeps the gate; only a successful read of the analysis lifts it", () => {
  const uncertain = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true },
                         { type: "run-unconfirmed", notice: lostReply }]);
  for (const notice of [lostReply, noticeFor({ state: "unconfirmed", status: 503, message: "Unexpected reply (503).",
                                                 error: null }), refused("not_found")]) {
    const after = run([{ type: "busy", busy: "reading" }, { type: "notice", notice }, { type: "approve", checked: true }],
                      uncertain);
    assert.equal(after.uncertain, true);
    assert.equal(mayRun(after), false);
    assert.deepEqual(panel(after), { kind: "uncertain" });
  }
});

test("a successful read after an uncertain run: a run that happened stays unrunnable, a prepared one starts afresh", () => {
  const uncertain = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true },
                         { type: "run-unconfirmed", notice: lostReply }]);
  const expected: Record<string, string> = { "analysis-running": "running", "analysis-recorded": "recorded",
    "analysis-failed": "held", "analysis-unresolved": "held", "analysis-not-sent": "not_sent" };
  for (const [name, kind] of Object.entries(expected)) {
    const ran = analysisOf(name);
    const after = run([{ type: "read", analysis: { ...ran, analysis_id: quoted.analysis_id, effort: quoted.effort } },
                       { type: "approve", checked: true }], uncertain);
    assert.deepEqual([after.uncertain, panel(after).kind, mayRun(after)], [false, kind, false], name);
  }
  // Prepared with no recorded attempt, under the server's active quote: the ordinary flow, approval not carried over.
  const prepared = reduce(uncertain, { type: "read", analysis: quoted });
  assert.deepEqual([prepared.uncertain, prepared.approved, panel(prepared)],
                   [false, false, { kind: "approve", quote: quoted.quote!, canRun: false }]);
  assert.equal(mayRun(reduce(prepared, { type: "approve", checked: true })), true);
});

test("while a run is uncertain the header says its outcome is unknown, until a successful read says what happened", () => {
  const unknown = { key: "uncertain", label: "Run outcome unknown", outcome: null };
  const approved = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true }]);
  assert.deepEqual(headerState(approved), { key: "prepared", label: "Prepared · not run", outcome: null });
  const uncertain = run([{ type: "busy", busy: "running" }, { type: "run-unconfirmed", notice: lostReply }], approved);
  assert.deepEqual(headerState(uncertain), unknown);  // Never the stale "Prepared · not run" of the last read.
  for (const notice of [lostReply, refused("not_found")]) {  // A failed read keeps the header with the gate.
    assert.deepEqual(headerState(run([{ type: "busy", busy: "reading" }, { type: "notice", notice }], uncertain)), unknown);
  }
  const ran = { ...recorded.analysis, analysis_id: quoted.analysis_id, effort: quoted.effort };
  assert.deepEqual(headerState(reduce(uncertain, { type: "read", analysis: ran })),
                   { key: "recorded", label: "Recorded", outcome: { key: "analysis", label: "Analysis recorded" } });
  assert.deepEqual(headerState(reduce(uncertain, { type: "read", analysis: quoted })),
                   { key: "prepared", label: "Prepared · not run", outcome: null });
  assert.equal(headerState(initialFlow), null);
});

test("a definite refusal before sending, or an unconfirmed quote reply, never gates the page", () => {
  const approved = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true }]);
  const definite = run([{ type: "notice", notice: refused("insufficient_credits") }, { type: "approve", checked: true }],
                       approved);
  assert.deepEqual([definite.uncertain, mayRun(definite)], [false, true]);
  const quoteLost = run([{ type: "read", analysis: prepared }, { type: "busy", busy: "quoting" },
                         { type: "notice", notice: lostReply }]);
  assert.deepEqual([quoteLost.uncertain, panel(quoteLost)], [false, { kind: "quote", previous: null, canQuote: true }]);
});

test("server-reported limits are advice beside the action, never a block on it", () => {
  assert.deepEqual(advisories(account, quote), []);
  const lines = advisories(readerB, { ...quote, credits: 6 });
  assert.equal(lines.length, 2);
  assert.match(lines.join(" "), /no analyses left today/);
  assert.match(lines.join(" "), /2 credits available, fewer than this quote's 6/);
  const approved = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true }]);
  assert.equal((panel(approved) as { canRun: boolean }).canRun, true);  // The server decides; the page does not count.
});

test("after an action, focus goes to what is new: the quote to approve, the result, or the state card", () => {
  const step = (from: FlowState, event: FlowEvent) => focusAfter(panel(from), panel(reduce(from, event)));
  const asking = run([{ type: "read", analysis: prepared }, { type: "busy", busy: "quoting" }]);
  assert.equal(step(asking, { type: "quoted", quote }), "quote");  // The Get-a-quote control is replaced by the quote.
  const sending = run([{ type: "read", analysis: quoted }, { type: "approve", checked: true }, { type: "busy", busy: "running" }]);
  assert.equal(step(sending, { type: "ran", analysis: recorded.analysis, duplicate: false }), "result");
  assert.equal(step(sending, { type: "ran", analysis: recorded.analysis, duplicate: true }), "result");
  assert.equal(step(sending, { type: "run-unconfirmed", notice: lostReply }), "state");
  assert.equal(step(sending, { type: "notice", notice: refused("quote_expired") }), "state");  // Back to asking for one.
  assert.equal(step(sending, { type: "ran", analysis: analysisOf("analysis-running"), duplicate: false }), "state");
  // Checking again: the result or another state once the server says so; nothing new, and focus stays on the control.
  const uncertain = reduce(sending, { type: "run-unconfirmed", notice: lostReply });
  assert.equal(step(uncertain, { type: "read", analysis: recorded.analysis }), "result");
  assert.equal(step(uncertain, { type: "read", analysis: prepared }), "state");
  const running = run([{ type: "read", analysis: analysisOf("analysis-running") }, { type: "busy", busy: "reading" }]);
  assert.equal(step(running, { type: "read", analysis: analysisOf("analysis-running") }), null);
  assert.equal(step(running, { type: "read", analysis: analysisOf("analysis-failed") }), "state");
  // The same quote read again or approved stays put; a different quote is new.
  const approving = run([{ type: "read", analysis: quoted }]);
  assert.equal(step(approving, { type: "approve", checked: true }), null);
  assert.equal(step(approving, { type: "read", analysis: quoted }), null);
  assert.equal(step(approving, { type: "quoted", quote: { ...quoted.quote!, quote_id: "SYNTHETIC-another-quote" } }), "quote");
  assert.equal(step(asking, { type: "notice", notice: lostReply }), null);  // A refused quote: the control is still there.
  assert.equal(focusAfter(panel(sending), panel(initialFlow)), null);
});

test("the allowance stands beside a decision still to make, and follows the result once none is left", () => {
  const beside = (state: FlowState) => allowanceBesideDecision(panel(state));
  assert.equal(beside(initialFlow), true);
  assert.equal(beside(run([{ type: "read", analysis: prepared }])), true);
  assert.equal(beside(run([{ type: "read", analysis: quoted }])), true);
  assert.equal(beside(run([{ type: "read", analysis: analysisOf("analysis-running") }])), true);
  assert.equal(beside(run([{ type: "read", analysis: quoted }, { type: "run-unconfirmed", notice: lostReply }])), true);
  for (const name of ["analysis-recorded", "analysis-failed", "analysis-unresolved", "analysis-not-sent"]) {
    assert.equal(beside(run([{ type: "read", analysis: analysisOf(name) }])), false, name);
  }
});
