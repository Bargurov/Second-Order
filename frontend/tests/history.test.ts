// The event overview's processing history: "not processed" stated as a valid state, uncertain sends named, costs kept
// apart (planning estimate, usage-derived, unverified billing), and a history of another version, or one claiming a
// provider call, refused. SYNTHETIC values shaped like the server's replies.
import assert from "node:assert/strict";
import test from "node:test";
import { HISTORY_STEP, costLine, fetchOverview, historyStatement, type ProcessingHistory } from "../src/eventOverview.ts";

const ITEM = "fed-monetary:0123456789abcdef0123";
const HISTORY: ProcessingHistory = {
  history_version: "event-history-0.1", provider_called: false, state: "not_processed",
  summary: { retrievals: 2, versions: 1, model_triage: 0, simulated_triage: 0, triage_requests: 0, captures: 0,
             drafts: 0, reviews: 0, frozen: 0, uncertain: 0, failed: 0 },
  steps: [], limitations: [],
};

test("the history says not processed as a valid state, and names uncertain sends", () => {
  assert.equal(historyStatement(HISTORY), "Not processed: listed by 2 recorded retrievals; no triage, analysis or " +
    "review is recorded. That is a valid state.");
  assert.equal(historyStatement({ ...HISTORY, summary: { ...HISTORY.summary, retrievals: 0 } }),
               "Not processed: with no recorded retrieval; no triage, analysis or review is recorded. That is a valid state.");
  const busy: ProcessingHistory = {
    ...HISTORY, state: "needs_attention",
    summary: { ...HISTORY.summary, versions: 2, simulated_triage: 1, captures: 1, drafts: 1, uncertain: 1 } };
  assert.equal(historyStatement(busy), "Listed by 2 recorded retrievals across 2 versions; 1 simulated triage result " +
    "(no model read it), 1 saved event, 1 recorded draft attempt. Needs attention: 1 uncertain send.");
  assert.match(HISTORY_STEP.use.empty, /Research intake is closed/);
});

test("a cost keeps the estimate, the usage-derived amount and unverified billing apart", () => {
  assert.equal(costLine({ estimate_usd: 0.0123, usage_usd: 0.0021, billing: "not_verified", basis: "For the whole request." }),
               "planning estimate $0.0123 · usage-derived $0.0021 · billing not verified. For the whole request.");
  assert.equal(costLine({ estimate_usd: 0.0123, usage_usd: null, billing: "not_verified", basis: "No usage was reported." }),
               "planning estimate $0.0123 · usage-derived: unknown · billing not verified. No usage was reported.");
  assert.equal(costLine({ estimate_usd: null, usage_usd: 0, billing: null, basis: "Local simulation." }),
               "usage-derived $0. Local simulation.");
  assert.match(costLine({ estimate_usd: 1.5, usage_usd: 0.2, billing: "not_verified", basis: "" }),
               /^planning estimate \$1\.50 · usage-derived \$0\.2000 · billing not verified\./);
});

test("an overview whose history is another version, or claims a provider call, is refused", async () => {
  const base = { overview_version: "event-overview-0.1", kind: "inbox", id: ITEM, provider_called: false };
  const reply = (body: unknown) => (async () => new Response(JSON.stringify(body), { status: 200 })) as typeof fetch;
  const original = globalThis.fetch;
  try {
    globalThis.fetch = reply({ ...base, history: HISTORY });
    assert.equal((await fetchOverview("inbox", ITEM)).state, "ready");
    globalThis.fetch = reply({ ...base, history: { ...HISTORY, history_version: "event-history-9" } });
    assert.equal((await fetchOverview("inbox", ITEM)).state, "error");
    globalThis.fetch = reply({ ...base, history: { ...HISTORY, provider_called: true } });
    assert.equal((await fetchOverview("inbox", ITEM)).state, "error");
  } finally {
    globalThis.fetch = original;
  }
});
