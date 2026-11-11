// The Client's actions (src/client/controller.ts) through the contract's own request helpers, with the isolated TEST
// transport (src/client/testing/recordingFetcher.ts) answering from SYNTHETIC fixtures and recording every request.
// MOCK: these prove what the page sends and how it reads replies, not what a real server enforces.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { USER_HEADER, approvalFor, userApi, type Analysis, type Quote } from "../src/contracts/user.ts";
import { NOT_APPROVED, outcomeOf, runApproved, runEvents } from "../src/client/controller.ts";
import { initialFlow, reduce, type FlowEvent, type FlowState } from "../src/client/flow.ts";
import { recordingFetcher, type Answer, type Recorded } from "../src/client/testing/recordingFetcher.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const errors = load<Record<string, object>>("user-contract-errors");
const quotedReply = load<{ analysis: Analysis }>("user-contract-analysis-quoted");
const quoted = quotedReply.analysis;
const quote = quoted.quote as Quote;
const ranReply = load<object>("user-contract-run-recorded");
const recordedReply = load<object>("user-contract-analysis-recorded");
const flow = (events: FlowEvent[], from: FlowState = initialFlow) => events.reduce(reduce, from);
const approved = flow([{ type: "read", analysis: quoted }, { type: "approve", checked: true }]);

function server(answer: Answer | ((request: Recorded) => Answer)) {
  const recorder = recordingFetcher(typeof answer === "function" ? answer : () => answer);
  return { api: userApi(recorder.fetcher), requests: recorder.requests };
}
const runs = (requests: Recorded[]) => requests.filter((item) => item.method === "POST" && item.path.endsWith("/runs"));

/** One page step: the run action, then what its reply does to the page (as AnalysisPage dispatches it). */
async function pressRun(api: ReturnType<typeof userApi>, state: FlowState): Promise<FlowState> {
  const event = runEvents(await runApproved(api, state));
  assert.notEqual(event.type, "session");
  return reduce(state, event as FlowEvent);
}

test("creating the request helpers sends nothing", () => {
  const { requests } = server({ status: 200, body: {} });
  assert.equal(requests.length, 0);
});

test("a run without the person's approval, or under a quote for another analysis, sends nothing", async () => {
  const { api, requests } = server({ status: 201, body: ranReply });
  const notApproved = flow([{ type: "read", analysis: quoted }]);
  assert.deepEqual(await runApproved(api, notApproved), { kind: "notice", notice: NOT_APPROVED });
  assert.deepEqual(await runApproved(api, { ...approved, quote: { ...quote, effort: "low" } }),
                   { kind: "notice", notice: NOT_APPROVED });
  assert.deepEqual(await runApproved(api, { ...approved, quote: null }), { kind: "notice", notice: NOT_APPROVED });
  assert.deepEqual(await runApproved(api, { ...approved, busy: "running" }), { kind: "notice", notice: NOT_APPROVED });
  assert.equal(requests.length, 0);
});

test("an approved run is one POST that repeats the quote exactly, with the user header", async () => {
  const { api, requests } = server({ status: 201, body: ranReply });
  const outcome = await runApproved(api, approved);
  assert.equal(outcome.kind, "ok");
  assert.equal(requests.length, 1);
  const [sent] = requests;
  assert.equal(sent.method, "POST");
  assert.equal(sent.path, `/api/user/analyses/${encodeURIComponent(quoted.analysis_id)}/runs`);
  assert.equal(sent.headers[USER_HEADER.toLowerCase()], "1");
  assert.deepEqual(sent.body, approvalFor(quote));
  assert.deepEqual(sent.body, { quote_id: quote.quote_id, effort: quote.effort, credits: quote.credits, approve: true });
  assert.equal(runEvents(outcome).type, "ran");
});

test("a lost reply or a server error is unconfirmed after exactly one request, never retried, and gates the page",
  async () => {
    for (const answer of ["no-reply", { status: 503, body: errors.sending_disabled },
                          { status: 500, body: errors.internal_error }] as Answer[]) {
      const { api, requests } = server(answer);
      const outcome = await runApproved(api, approved);
      assert.equal(requests.length, 1, JSON.stringify(answer));
      assert.ok(outcome.kind === "notice" && outcome.notice.tone === "unconfirmed" && outcome.notice.next === "read_again");
      assert.equal(runEvents(outcome).type, "run-unconfirmed");
    }
  });

test("after an unconfirmed run, no second run is sent until a read of the analysis succeeds", async () => {
  let readsFail = true;
  const { api, requests } = server((request) => {
    if (request.method === "GET") return readsFail ? { status: 503, body: errors.internal_error } : { status: 200, body: quotedReply };
    return runs(requests).length === 1 ? "no-reply" : { status: 201, body: ranReply };
  });
  let state = await pressRun(api, approved);  // The first run: its reply is lost.
  assert.equal(runs(requests).length, 1);
  assert.equal(state.uncertain, true);
  state = reduce(state, { type: "approve", checked: true });  // The person ticks the approval again and presses Run.
  state = await pressRun(api, state);
  assert.equal(runs(requests).length, 1, "a second run was sent before any read");
  // A failed read keeps the gate.
  const failedRead = outcomeOf(await api.analysis(quoted.analysis_id));
  assert.equal(failedRead.kind, "notice");
  if (failedRead.kind === "notice") state = reduce(state, { type: "notice", notice: failedRead.notice });
  state = await pressRun(api, reduce(state, { type: "approve", checked: true }));
  assert.equal(runs(requests).length, 1, "a second run was sent after a failed read");
  // A successful read showing the analysis still prepared, with nothing recorded, restores the ordinary flow.
  readsFail = false;
  const goodRead = outcomeOf(await api.analysis(quoted.analysis_id));
  assert.equal(goodRead.kind, "ok");
  if (goodRead.kind === "ok") state = reduce(state, { type: "read", analysis: goodRead.data.analysis });
  assert.equal(state.approved, false);  // A fresh decision, not the earlier approval.
  state = await pressRun(api, reduce(state, { type: "approve", checked: true }));
  assert.equal(runs(requests).length, 2);
  assert.deepEqual(runs(requests)[1].body, approvalFor(quote));
});

test("a read showing the run was recorded keeps Run unavailable", async () => {
  const { api, requests } = server((request) => request.method === "GET" ? { status: 200, body: recordedReply } : "no-reply");
  let state = await pressRun(api, approved);
  const read = outcomeOf(await api.analysis(quoted.analysis_id));
  if (read.kind === "ok") state = reduce(state, { type: "read", analysis: read.data.analysis });
  state = await pressRun(api, reduce(state, { type: "approve", checked: true }));
  assert.deepEqual([state.uncertain, runs(requests).length], [false, 1]);
});

test("a definite refusal before sending does not gate: approving again sends a new request", async () => {
  const { api, requests } = server({ status: 409, body: errors.insufficient_credits });
  let state = await pressRun(api, approved);
  assert.equal(state.uncertain, false);
  state = await pressRun(api, reduce(state, { type: "approve", checked: true }));
  assert.equal(runs(requests).length, 2);
});

test("refusals keep their code and next step; a 401 ends the session", async () => {
  const cases: [string, number, string][] = [["quote_expired", 409, "new_quote"], ["insufficient_credits", 409, "ask_admin"],
    ["daily_limit_reached", 409, "none"], ["unsupported_effort", 409, "choose_effort"]];
  for (const [code, status, next] of cases) {
    const { api, requests } = server({ status, body: errors[code] });
    const outcome = await runApproved(api, approved);
    assert.equal(requests.length, 1, code);
    assert.ok(outcome.kind === "notice" && outcome.notice.code === code && outcome.notice.next === next, code);
    assert.equal(runEvents(outcome).type, "notice", code);
  }
  const { api } = server({ status: 401, body: errors.session_expired });
  assert.deepEqual(outcomeOf(await api.account()), { kind: "session", reason: "session_expired" });
  assert.deepEqual(runEvents(await runApproved(api, approved)), { type: "session", reason: "session_expired" });
});

test("a reply carrying an administrator-only field is not shown, and gates the run as unconfirmed", async () => {
  const leaky = structuredClone(ranReply) as { analysis: Record<string, unknown> };
  leaky.analysis.usage = { input: 1 };
  const { api } = server({ status: 201, body: leaky });
  const outcome = await runApproved(api, approved);
  assert.equal(outcome.kind, "notice");
  assert.match(outcome.kind === "notice" ? outcome.notice.detail : "", /administrator-only field/);
  assert.equal(runEvents(outcome).type, "run-unconfirmed");
});
