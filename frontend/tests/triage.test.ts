// Headline triage client: selection views verified before use, explicit POSTs with the triage header, a bounded
// selection, and grouped and ungrouped views that keep every entry exactly once and never merge suggestions from
// different responses. The views are the backend's captured payloads (frontend/tests/fixtures/triage-*.json, written
// by tests/test_headline_triage.py); all feed content in them is SYNTHETIC.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type { InboxItem } from "../src/inbox.ts";
import {
  MAX_SELECTION, approveRequest, attemptLabel, currentEntry, feedDateNote, fetchRequests, fetchSelection,
  groupedSections, listedLabel, previewTriage, recheckLabel, recheckOutcome, sameEntries, scopeNote, sendOutcome,
  statusLabel, toggled, triageRows, verifiedSelection, type SelectionView, type TriageAttempt, type TriageRelation,
} from "../src/triage.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));
const captured = (): any => structuredClone(fixture("triage-selection.json"));
const STATEMENT = "Federal Reserve issues FOMC statement";

async function withFetch<T>(fake: typeof fetch, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = fake;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

const answer = (status: number, body: unknown) => async () =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("the captured selection view verifies: saved results reused, only missing work planned", () => {
  const view = verifiedSelection(captured());
  assert.ok(view);
  assert.equal(view.items.length, 9);
  assert.equal(view.plan.requests, 1);
  assert.equal(view.plan.reused.length, 6);
  assert.deepEqual(view.plan.entries, view.items.filter((row) => row.status === "process").map((row) => row.input.id));
  assert.ok(view.items.filter((row) => row.status === "reuse").every((row) => row.result && row.provenance?.current_config));
  assert.ok(view.plan.cost_estimate!.comparison_context_tokens_assumed > 0);
  assert.equal(view.modes.paid.enabled, false);
});

test("anything unexpected in a selection view is refused", () => {
  const changes: [string, (view: any) => void][] = [
    ["another view version", (v) => { v.view_version = "headline-triage-view-0.1"; }],
    ["an unknown mode", (v) => { v.mode = "free"; }],
    ["no entries", (v) => { v.items = []; }],
    ["a repeated entry", (v) => { v.items.push(structuredClone(v.items[0])); }],
    ["a link off the publishers' hosts", (v) => { v.items[0].input.link = "https://example.com/release"; }],
    ["an undocumented status", (v) => { v.items[0].status = "cached"; }],
    ["a reused entry without its result", (v) => { v.items.find((r: any) => r.status === "reuse").result = null; }],
    ["a reused result from an earlier version", (v) => {
      v.items.find((r: any) => r.status === "reuse").provenance.current_config = false; }],
    ["a category outside the taxonomy", (v) => {
      v.items.find((r: any) => r.status === "reuse").result.category = "Market moving"; }],
    ["an entry to triage marked as context", (v) => { v.items.find((r: any) => r.status === "process").in_request = "context"; }],
    ["planned entries that differ from the rows", (v) => { v.plan.entries.pop(); }],
    ["a planned comparison outside the selection", (v) => { v.plan.pairs.needed.push([v.items[0].input.id, "x:1"]); }],
    ["a planned comparison of one entry with itself", (v) => { v.plan.pairs.needed.push([v.items[0].input.id, v.items[0].input.id]); }],
    ["no planned request but a request ID", (v) => { v.plan.requests = 0; v.plan.entries = []; }],
    ["a relation to an unknown entry", (v) => { v.relations[0].item_ids.push("bls-cpi:00000000000000000000"); }],
    ["a one-entry relation", (v) => { v.relations[0].item_ids.splice(1); }],
    ["a relation without provenance", (v) => { delete v.relations[0].provenance; }],
    ["a relation that does not say whether its scope was checked", (v) => { delete v.relations[0].scope_checked; }],
    ["a planned request without an estimate", (v) => { v.plan.cost_estimate = null; }],
    ["a mode flag that is not a boolean", (v) => { v.modes.paid.enabled = "no"; }],
  ];
  for (const [name, change] of changes) {
    const view = captured();
    change(view);
    assert.equal(verifiedSelection(view), null, name);
  }
});

test("relations say when they were not checked against a planned comparison scope", () => {
  const view = captured();
  assert.ok(view.relations.length > 0 && view.relations.every((relation: any) => relation.scope_checked === true));
  assert.equal(scopeNote(view.relations[0]), "");  // Today's relations: limited to the request's own pairs.
  const earlier = { ...view.relations[0], scope_checked: false };
  assert.match(scopeNote(earlier), /earlier triage contract, whose replies were not limited/);
  assert.ok(verifiedSelection({ ...view, relations: [earlier] }));  // Shown, labelled, never relabelled as checked.
});

test("the message after a send comes from the recorded attempt, never from an empty plan", () => {
  const base = { mode: "paid", attempt: "paid", state: "complete" as const, outcome_note: "Note.", sent_at: "2026-10-09T15:20:38+00:00",
                 received_at: "2026-10-09T15:20:57+00:00", request_id: "req_x", cost: null, validation_policy: "triage-validation-1" };
  const rejected: TriageAttempt = { ...base, outcome: "not_accepted", message: "The summary of result 4 is longer than 25 words" };
  const shown = sendOutcome("paid", rejected);
  assert.equal(shown.tone, "error");
  assert.match(shown.text, /recorded but not accepted: The summary of result 4 is longer than 25 words\. Nothing from it/);
  assert.doesNotMatch(shown.text, /passed validation|accepted under/);
  const accepted = sendOutcome("simulated", { ...base, mode: "simulated", outcome: "triaged", message: null,
                                              validation_policy: "triage-validation-2" });
  assert.deepEqual([accepted.tone, /accepted under triage-validation-2/.test(accepted.text)], ["done", true]);
  for (const attempt of [undefined, { mode: "paid", attempt: "paid", state: "none" as const },
                         { mode: "paid", attempt: "paid", state: "incomplete" as const, sent: true, detail: "Sent; no response recorded." },
                         { ...base, outcome: "no_reply" as const, message: "No reply arrived (ReadTimeout). The outcome is unknown." },
                         { ...base, outcome: "provider_error" as const, message: "The provider answered HTTP 500" }]) {
    assert.equal(sendOutcome("paid", attempt as TriageAttempt | undefined).tone, "error", JSON.stringify(attempt));
  }
});

test("a local re-check says plainly what it did and labels what it accepted", () => {
  const accepted = recheckOutcome({ state: "complete", validation_policy: "triage-validation-2", current_policy: true,
                                    outcome: "accepted", message: null, revalidated_at: "2026-10-09T16:00:00+00:00" });
  assert.equal(accepted.tone, "done");
  assert.match(accepted.text, /Nothing was sent or regenerated/);
  assert.match(accepted.text, /original record of it as not accepted is unchanged/);
  const still = recheckOutcome({ state: "complete", validation_policy: "triage-validation-2", current_policy: true,
                                 outcome: "not_accepted", message: "1 of the 2 supplied items have no result" });
  assert.deepEqual([still.tone, /Still not accepted/.test(still.text)], ["error", true]);
  assert.equal(recheckOutcome(null).tone, "error");
  const view = captured();
  const row = view.items.find((item: any) => item.provenance);
  assert.equal(recheckLabel(row.provenance), "");  // Accepted on receipt: no label.
  const rechecked = { ...row.provenance, revalidation: { validation_policy: "triage-validation-2",
    revalidated_at: "2026-10-09T16:00:00+00:00", original_outcome: "not_accepted",
    original_validation_policy: "triage-validation-1", original_message: "The summary of result 4 is longer than 25 words" } };
  assert.match(recheckLabel(rechecked), /accepted on a local re-check under triage-validation-2 \(2026-10-09 16:00 UTC\), after it was not accepted on receipt under triage-validation-1; generated by this request's original response, not regenerated or re-sent/);
  assert.ok(verifiedSelection({ ...view, items: view.items.map((item: any) => item === row ? { ...row, provenance: rechecked } : item) }));
  assert.equal(verifiedSelection({ ...view, items: view.items.map((item: any) => item === row
    ? { ...row, provenance: { ...row.provenance, validation_policy: undefined } } : item) }), null);
});

test("the grouped view keeps every entry exactly once and groups only as a response stated", () => {
  const view = verifiedSelection(captured())!;
  const sections = groupedSections(view);
  const placed = sections.flatMap((section) => section.kind === "group" ? section.rows.map((row) => row.input.id)
    : [section.row.input.id]);
  assert.deepEqual(placed.slice().sort(), view.items.map((row) => row.input.id).sort());
  assert.equal(placed.length, view.items.length);
  const groups = sections.filter((section) => section.kind === "group");
  assert.equal(groups.length, 1);
  // The recurring title on two meeting dates is never grouped.
  const statements = view.items.filter((row) => row.input.title === STATEMENT).map((row) => row.input.id);
  assert.equal(statements.length, 2);
  assert.ok(groups.every((group) => group.kind === "group" && !statements.every((id) => group.relation.item_ids.includes(id))));
  // A correction stays its own entry, with a note naming what it corrects.
  const correction = triageRows(view).find((row) => row.result?.category === "Update or correction")!;
  assert.deepEqual(correction.notes.map((note) => note.relation.relation), ["update_or_correction"]);
  assert.ok(correction.notes[0].others.every((other) => other.title === STATEMENT));
});

test("suggestions from different responses that share an entry are never merged or chained", () => {
  const view = verifiedSelection(captured())!;
  const [a, b, c] = view.items.map((row) => row.input.id);
  const base = view.relations[0];
  const relation = (ids: string[], triage: string): TriageRelation => ({
    ...base, relation: "possibly_same_event", label: "Possibly the same event", item_ids: ids, reason: "r",
    provenance: { ...base.provenance, triage_id: triage },
  });
  const overlapping: SelectionView = { ...view, relations: [relation([a, b], "triage-" + "1".repeat(24)),
                                                             relation([b, c], "triage-" + "2".repeat(24))] };
  const sections = groupedSections(overlapping);
  const groups = sections.filter((section) => section.kind === "group");
  assert.deepEqual(groups.map((group) => group.kind === "group" && group.rows.map((row) => row.input.id)), [[a, b]]);
  const placed = sections.flatMap((section) => section.kind === "group" ? section.rows : [section.row]);
  assert.equal(new Set(placed.map((row) => row.input.id)).size, view.items.length);
  const bRow = placed.find((row) => row.input.id === b)!;
  assert.deepEqual(bRow.notes.map((note) => [note.relation.provenance.triage_id.slice(-1), note.unmerged]), [["2", true]]);
  // Ungrouped, both suggestions are notes and nothing is marked as unmerged.
  assert.ok(triageRows(overlapping).flatMap((row) => row.notes).every((note) => !note.unmerged));
});

test("statuses say plainly what each entry has", () => {
  const view = verifiedSelection(captured())!;
  const labels = new Set(view.items.map(statusLabel));
  assert.deepEqual([...labels].sort(), ["Needs a result", "Saved result reused"]);
  assert.equal(statusLabel({ ...view.items[0], status: "unresolved" }), "Earlier attempt unresolved");
  assert.equal(statusLabel({ ...view.items[0], status: "earlier_version" }), "Saved result from an earlier version");
  assert.equal(statusLabel({ ...view.items[0], status: "process", reprocess: true }), "Requested again by you");
});

test("a selection holds at most 25 entries and toggles one entry at a time", () => {
  let selected: string[] = [];
  for (let n = 0; n < 30; n++) selected = toggled(selected, `fed-monetary:${String(n).padStart(20, "0")}`);
  assert.equal(selected.length, MAX_SELECTION);
  assert.equal(toggled(selected, selected[3]).length, MAX_SELECTION - 1);
  assert.ok(sameEntries(["a", "b"], ["b", "a"]));
  assert.ok(!sameEntries(["a", "b"], ["a", "c"]));
});

test("feed dates are always described as feed metadata, with missing and differing dates said plainly", () => {
  const relation = verifiedSelection(captured())!.relations[0];
  assert.match(feedDateNote({ ...relation, feed_dates: { distinct_utc_dates: ["2026-07-29", "2026-09-16"], without_timestamp: 0, note: "" } }),
               /^Feed dates 2026-07-29, 2026-09-16; the dates differ\. Feed timestamps are feed metadata/);
  assert.equal(feedDateNote({ ...relation, feed_dates: { distinct_utc_dates: [], without_timestamp: 2, note: "" } }),
               "No feed dates; 2 entries have no feed timestamp. Feed timestamps are feed metadata, not verified publication times.");
});

test("Analyze this event uses the held entry as it is now, retained included, and nothing once it is gone", () => {
  const input = verifiedSelection(captured())!.items[0].input;
  const retained = { id: input.id, title: input.title, link: input.link, history: true } as InboxItem;
  assert.equal(currentEntry(input, [retained]), retained);
  assert.equal(currentEntry(input, []), null);
  assert.equal(currentEntry(input, [{ ...retained, link: "http://www.federalreserve.gov/x.htm" }]), null);
});

test("previews and approvals are explicit POSTs with the triage header; reads are plain GETs", async () => {
  const view = captured() as SelectionView;
  const calls: { url: string; init?: RequestInit }[] = [];
  const fake = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url === "/api/triage" && init?.method !== "POST") return answer(200, fixture("triage-listing.json"))();
    if (url.includes("/simulated") || url.includes("/paid")) return answer(201, { view_version: view.view_version })();
    return answer(200, view)();
  }) as unknown as typeof fetch;
  const paidView = { ...view, mode: "paid", plan: { ...view.plan, reprocess: [view.items[0].input.id] } } as SelectionView;
  await withFetch(fake, async () => {
    assert.equal((await previewTriage(["fed-monetary:a", "bls-cpi:b"], "simulated", [])).state, "done");
    assert.equal((await approveRequest(view)).state, "done");
    assert.equal((await approveRequest(paidView)).state, "done");
    assert.equal((await fetchSelection(["fed-monetary:a", "bls-cpi:b"], "paid", ["bls-cpi:b"])).state, "ready");
    assert.equal((await fetchRequests()).state, "ready");
  });
  const [previewed, simulated, paid, read, listed] = calls;
  for (const call of [previewed, simulated, paid]) {
    assert.equal(call.init?.method, "POST");
    assert.equal((call.init?.headers as Record<string, string>)["X-Second-Order-Triage"], "1");
  }
  assert.deepEqual(JSON.parse(String(previewed.init?.body)), { item_ids: ["fed-monetary:a", "bls-cpi:b"], mode: "simulated",
                                                               reprocess_ids: [] });
  assert.equal(simulated.url, `/api/triage/${view.plan.triage_id}/simulated`);
  assert.deepEqual(JSON.parse(String(simulated.init?.body)),
                   { request_sha256: view.plan.request_sha256, approve_simulated_response: true, reprocess_ids: [],
                     comparison_pairs: view.plan.pairs.needed });
  assert.ok(view.plan.pairs.needed.length > 0);  // The planned comparisons travel with the approval.
  assert.equal(paid.url, `/api/triage/${view.plan.triage_id}/paid`);
  assert.deepEqual(JSON.parse(String(paid.init?.body)), {
    request_sha256: view.plan.request_sha256, approve_paid_request: true, reprocess_ids: [view.items[0].input.id],
    comparison_pairs: view.plan.pairs.needed,
    estimated_max_usd: view.plan.cost_estimate!.estimated_paid_if_output_reaches_max_usd });
  assert.equal(read.url, "/api/triage/selection?mode=paid&ids=fed-monetary%3Aa&ids=bls-cpi%3Ab&reprocess=bls-cpi%3Ab");
  for (const call of [read, listed]) assert.equal(call.init?.method, undefined);
});

test("refusals, lost replies and unverifiable replies are reported honestly, and nothing is retried", async () => {
  const view = captured() as SelectionView;
  let calls = 0;
  const cases: [typeof fetch, string][] = [
    [answer(409, { detail: "An earlier simulated request already claimed this entry" }) as unknown as typeof fetch, "failed"],
    [answer(500, { detail: "The simulated attempt was interrupted" }) as unknown as typeof fetch, "unconfirmed"],
    [answer(201, { view_version: "something else" }) as unknown as typeof fetch, "unconfirmed"],
    [(async () => { throw new TypeError("offline"); }) as unknown as typeof fetch, "unconfirmed"],
  ];
  for (const [fake, expected] of cases) {
    const counted = (async (...args: Parameters<typeof fetch>) => { calls++; return fake(...args); }) as typeof fetch;
    const result = await withFetch(counted, () => approveRequest(view));
    assert.equal(result.state, expected);
    assert.ok(result.state !== "done" && result.message.length > 0);
  }
  assert.equal(calls, cases.length);  // One request per action, never a second.
});

test("attempt and listing labels never overstate what was recorded; failed attempts stay listed", () => {
  assert.equal(attemptLabel({ mode: "paid", attempt: "paid", state: "none" }), "Not requested");
  assert.equal(attemptLabel({ mode: "paid", attempt: "paid", state: "incomplete", detail: "d", sent: true }),
               "Sent, no response recorded");
  assert.equal(listedLabel({ state: "complete", outcome: "triaged" }), "accepted");
  assert.equal(listedLabel({ state: "complete", outcome: "no_reply" }), "no reply");
  assert.equal(listedLabel({ state: "none", outcome: null }), "not requested");
  const listing = fixture("triage-listing.json");
  assert.equal(listing.requests.length, 1);
  assert.equal(listedLabel(listing.requests[0].attempts.simulated), "accepted");
  assert.equal(listing.requests[0].item_ids.length, 6);
});
