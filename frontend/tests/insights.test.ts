// Treasury findings client logic: replies read fail-closed, findings must cite measures shown, honest status wording,
// routes, and a lost reply that is never sent again.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  INSIGHT_VIEW_VERSION, bp, isListing, isOccasion, occasionHref, occasionStatus, rankText, runCheck,
} from "../src/insights.ts";
import { matchRoute } from "../src/routes.ts";

const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; });
const SHA = "a".repeat(64);

function measure(key: string) {
  return { key, measure: key.split(":")[0], label: key, window: key.split(":")[1], window_label: "w", span: 2,
           start: { date: "2026-09-15", values: [] }, end: { date: "2026-09-17", values: [] }, change_bp: "0",
           rank: "0.5000", smaller: 0, equal: 250, eligible: 250, candidates: 250, reference_first_end: null,
           reference_last_end: null, problem: null };
}

function occasion(findings: string[][], day = "2026-09-16") {
  return { view_version: INSIGHT_VIEW_VERSION, date: day, events: [], scope: "", limitations: [], bases: {},
           origins: {}, state: "checked", detail: null,
           result: { date: day, summary: "", measures: ["n10:W1", "r10:W1", "be10:W1"].map(measure),
                     findings: findings.map((observations) => ({ check: "R1:10:W1", observations })) } };
}

test("a listing is read only at this version, writing nothing and calling no provider", () => {
  const listing = { view_version: INSIGHT_VIEW_VERSION, occasions: [{ date: "2026-09-16", result_id: SHA }], events: [],
                    written: false, provider_called: false };
  assert.equal(isListing(listing), true);
  assert.equal(isListing({ ...listing, view_version: "insight-view-0.0" }), false);
  assert.equal(isListing({ ...listing, provider_called: true }), false);
  assert.equal(isListing({ ...listing, occasions: [{ date: "16 Sep", result_id: SHA }] }), false);
  assert.equal(isListing({ ...listing, occasions: [{ date: "2026-09-16", result_id: null }] }), true);
});

test("an occasion is read only for the date asked, and every finding must cite measures it shows", () => {
  assert.equal(isOccasion(occasion([["n10:W1", "r10:W1", "be10:W1"]]), "2026-09-16"), true);
  assert.equal(isOccasion(occasion([["n10:W1", "n2:W5"]]), "2026-09-16"), false);  // n2:W5 is not shown.
  assert.equal(isOccasion(occasion([[]]), "2026-09-16"), false);
  assert.equal(isOccasion(occasion([]), "2026-09-17"), false);
  assert.equal(isOccasion({ ...occasion([]), result: null }, "2026-09-16"), true);  // An unavailable occasion.
});

test("statuses say what was found, that nothing met the rules, or why nothing was measured", () => {
  assert.equal(occasionStatus({ state: "checked", findings: 2, detail: null }), "2 findings");
  assert.equal(occasionStatus({ state: "checked", findings: 0, detail: null }), "Checked · nothing met the rules");
  assert.equal(occasionStatus({ state: "unavailable", detail: "The retained data end on 2026-09-30." }),
               "Not measured: The retained data end on 2026-09-30.");
  assert.equal(bp("12"), "+12 bp");
  assert.equal(bp("-3.5"), "-3.5 bp");
  assert.equal(bp("0"), "0 bp");
  assert.equal(bp(null), "unavailable");
  assert.equal(rankText({ rank: "0.9300", smaller: 232, equal: 1, eligible: 250 }), "0.93 (exceeds 232 and equals 1 of 250)");
  assert.equal(rankText({ rank: null, smaller: null, equal: null, eligible: null }), "no rank");
});

test("findings routes", () => {
  assert.deepEqual(matchRoute("/findings"), { page: "findings" });
  assert.deepEqual(matchRoute(occasionHref("2026-09-16")), { page: "findings-occasion", day: "2026-09-16" });
  assert.deepEqual(matchRoute("/findings/16-09-2026"), { page: "not-found", reason: "unknown" });
});

test("a lost reply to a check is unconfirmed and never sent again", async () => {
  let calls = 0;
  globalThis.fetch = (async () => { calls += 1; throw new TypeError("network down"); }) as typeof fetch;
  assert.equal((await runCheck()).state, "unconfirmed");
  assert.equal(calls, 1);
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "No accepted H.15 release package" }),
                                               { status: 409 })) as typeof fetch;
  const refused = await runCheck();
  assert.equal(refused.state === "refused" && refused.message, "No accepted H.15 release package");
});
