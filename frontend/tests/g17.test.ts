// Industry findings client logic: replies read fail-closed, cards must cite releases and Table 1 sources they show,
// printed zeros keep their decimal, percentage points, routes, and a lost check reply that is never sent again.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  G17_INSIGHTS_HEADER, G17_VIEW_VERSION, breadthMonthOk, isG17Listing, isG17Tables, points, rate, rowName,
  runG17Check,
} from "../src/g17.ts";
import { INSIGHTS_HEADER } from "../src/insights.ts";
import { matchRoute } from "../src/routes.ts";

const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; });
const SHA = "a".repeat(64);
const URL1 = "https://www.federalreserve.gov/releases/g17/20260918/table1.htm";

function observed(path: string, release = "20260918") {
  return { label: path, path, naics: null, rate: ".7", rate_text: "+0.7%", month: "2026-07",
           column: "Monthly rate / 2026 / July[r]", marker: "r", table: "Table 1", url: URL1, sha256: SHA, release,
           release_date_as_stated: "September 18, 2026" };
}

function listing(overrides: Record<string, unknown> = {}) {
  return {
    view_version: G17_VIEW_VERSION, scope: "", limitations: [], available: ["20260918"], written: false,
    provider_called: false, state: "checked", detail: null, check: { check_id: SHA, checked_at: "", selection: [] },
    releases: [{ release: "20260918", extract_id: SHA, sources: [{ sha256: SHA }] }], table1: null,
    divergence: { order: "", comparisons: 1, counts: {}, total: 1, no_direction_parents: [],
                  shown: [{ month: "2026-07", observed: [observed("A / B"), observed("A")] }] },
    revisions: { order: "", counts: {}, total: 0, shown: [], printed_zero_transitions: [] },
    ...overrides,
  };
}

test("a listing is read only at this version, writing nothing and calling no provider", () => {
  assert.equal(isG17Listing(listing()), true);
  assert.equal(isG17Listing({ ...listing(), view_version: "g17-view-0.0" }), false);
  assert.equal(isG17Listing({ ...listing(), provider_called: true }), false);
  assert.equal(isG17Listing({ ...listing(), state: "not_checked", divergence: null, revisions: null }), true);
  assert.equal(isG17Listing({ ...listing(), state: "problem", divergence: listing().divergence }), false);
});

test("cards must cite releases the reply shows and Table 1 sources with their hashes", () => {
  const other = listing({ divergence: { ...listing().divergence, shown: [{ month: "2026-07",
    observed: [observed("A / B", "20260818"), observed("A")] }] } });
  assert.equal(isG17Listing(other), false);
  const table2 = listing({ divergence: { ...listing().divergence, shown: [{ month: "2026-07",
    observed: [{ ...observed("A / B"), table: "Table 2" }, observed("A")] }] } });
  assert.equal(isG17Listing(table2), false);
  const month = listing({ divergence: { ...listing().divergence, shown: [{ month: "2026-08",
    observed: [observed("A / B"), observed("A")] }] } });
  assert.equal(isG17Listing(month), false);
  const more = listing({ divergence: { ...listing().divergence, total: 0 } });
  assert.equal(isG17Listing(more), false);
});

test("full tables are read only when every cell names a listed month", () => {
  const tables = { view_version: G17_VIEW_VERSION, written: false, provider_called: false, state: "checked",
                   months: [{ key: "2026-07", label: "July 2026" }],
                   releases: [{ comparisons: [{ month: "2026-07" }] }],
                   revision_rows: [{ cells: [{ month: "2026-07" }] }] };
  assert.equal(isG17Tables(tables), true);
  assert.equal(isG17Tables({ ...tables, revision_rows: [{ cells: [{ month: "2026-08" }] }] }), false);
  assert.equal(isG17Tables({ ...tables, releases: [{}] }), false);
});

test("printed rates keep their decimal and differences are percentage points", () => {
  assert.equal(rate(".7"), "+0.7%");
  assert.equal(rate("-2.1"), "−2.1%");
  assert.equal(rate(".0"), "0.0%");
  assert.equal(rate("-.0"), "0.0%");
  assert.equal(rate(null), "not printed");
  assert.equal(points("-2.8"), "−2.8 pp");
  assert.equal(points("0.8"), "+0.8 pp");
  assert.equal(points(null), "—");
  assert.equal(rowName("INDUSTRY GROUP / Manufacturing / Machinery", "333"), "Machinery (NAICS 333)");
  assert.equal(rowName("INDUSTRY GROUP / Manufacturing", null), "Manufacturing");
  assert.equal(rowName("INDUSTRY GROUP / Manufacturing / Other manufacturing (non-NAICS)", "1133,5131pt."),
               "Other manufacturing (non-NAICS) (codes 1133,5131pt.)");
});

test("the check sends the same insights header as the Treasury check", () => {
  assert.equal(G17_INSIGHTS_HEADER, INSIGHTS_HEADER);
});

test("findings routes", () => {
  assert.deepEqual(matchRoute("/findings/g17"), { page: "findings-g17" });
  assert.deepEqual(matchRoute("/findings/2026-09-16"), { page: "findings-occasion", day: "2026-09-16" });
  assert.deepEqual(matchRoute("/findings/g18"), { page: "not-found", reason: "unknown" });
});

test("a lost reply to a check is unconfirmed and never sent again", async () => {
  let calls = 0;
  globalThis.fetch = (async () => { calls += 1; throw new TypeError("network down"); }) as typeof fetch;
  assert.equal((await runG17Check()).state, "unconfirmed");
  assert.equal(calls, 1);
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "No retained G.17 release" }),
                                               { status: 409 })) as typeof fetch;
  const refused = await runG17Check();
  assert.equal(refused.state === "refused" && refused.message, "No retained G.17 release");
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function breadthMonth(overrides: Record<string, unknown> = {}): any {
  return { month: "2026-04", month_label: "April 2026", column: "Monthly rate / 2026 / Apr.[r]", marker: "r",
           expected: 19, counts: { positive: 7, negative: 10, printed_zero: 2, missing: 0 },
           groups: { durable: { positive: 0, negative: 10, printed_zero: 1, missing: 0, expected: 11 },
                     nondurable: { positive: 7, negative: 0, printed_zero: 1, missing: 0, expected: 8 } },
           aggregate_rate: ".3", aggregate_rate_text: "+0.3%", state: "majority_down", state_text: "", counts_text: "",
           aggregate_vs_breadth: true, shares: { positive: "37%", negative: "53%", printed_zero: "11%" },
           members: { positive: [], negative: [], printed_zero: [], missing: [] }, ...overrides };
}

test("a breadth month is read only when its counts make up the 19 and claims need completeness", () => {
  assert.equal(breadthMonthOk(breadthMonth()), true);
  assert.equal(breadthMonthOk(breadthMonth({ counts: { positive: 7, negative: 10, printed_zero: 1, missing: 0 } })), false);
  const missing = { counts: { positive: 6, negative: 12, printed_zero: 0, missing: 1 }, state: "incomplete",
                    shares: null, aggregate_vs_breadth: false };
  assert.equal(breadthMonthOk(breadthMonth(missing)), true);
  assert.equal(breadthMonthOk(breadthMonth({ ...missing, shares: { positive: "", negative: "", printed_zero: "" } })), false);
  assert.equal(breadthMonthOk(breadthMonth({ ...missing, aggregate_vs_breadth: true })), false);
  assert.equal(breadthMonthOk(breadthMonth({ ...missing, state: "majority_down" })), false);
  assert.equal(breadthMonthOk(breadthMonth({ expected: 18 })), false);
});

test("a listing whose breadth does not verify is not read", () => {
  const latest = { release: "20260918", release_date_as_stated: "", url: "", sha256: SHA, table: "Table 1",
                   state: "computed", detail: null, months: [breadthMonth()] };
  const breadth = { state: "checked", detail: null, definitions: {}, latest, total: 0, shown: [] };
  assert.equal(isG17Listing(listing({ breadth })), true);
  assert.equal(isG17Listing(listing({ breadth: { ...breadth, latest: { ...latest, months: [breadthMonth({
    counts: { positive: 1, negative: 1, printed_zero: 1, missing: 0 } })] } } })), false);
  assert.equal(isG17Listing(listing({ breadth: { state: "not_checked", detail: "", definitions: {} } })), true);
});
