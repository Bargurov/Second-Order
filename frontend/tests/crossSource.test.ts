// Cross-source comparisons client logic, against the view the backend serves for the SYNTHETIC scenario (captured by
// tests/test_cross_source.py into fixtures/cross-source-view.json): read fail-closed, every EIA figure and sign label
// recomputed from its own values, G.17 cells tied to listed releases, the breakdown adding up, and a lost computation
// reply never sent again.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, test } from "node:test";
import {
  CROSS_SOURCE_INSIGHTS_HEADER, CROSS_SOURCE_VIEW_VERSION, eiaOk, expectedSigns, isCrossSourceView, printed, rateSign,
  runCrossSourceCheck, units, type CrossSourceView,
} from "../src/crossSource.ts";
import { units as electricityUnits } from "../src/electricity.ts";
import { INSIGHTS_HEADER } from "../src/insights.ts";

const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; });
const served: CrossSourceView = JSON.parse(readFileSync(new URL("./fixtures/cross-source-view.json", import.meta.url),
  "utf8"));
const copy = (): CrossSourceView => structuredClone(served);
const row = (view: CrossSourceView, period: string) =>
  view.comparisons!.industrial_vs_manufacturing.find((item) => item.period === period)!;
const utility = (view: CrossSourceView, period: string) =>
  view.comparisons!.utility_output_and_customers.find((item) => item.period === period)!;

test("the served view is read, with its periods, signs and coverage", () => {
  assert.equal(served.view_version, CROSS_SOURCE_VIEW_VERSION);
  assert.equal(isCrossSourceView(served), true);
  assert.deepEqual(served.periods.map((p) => p.key), ["2023-Q4", "2024-Q4", "2025-Q4", "2026-06", "2026-07", "2026-08"]);
  assert.deepEqual(served.comparisons!.industrial_vs_manufacturing.map((r) => r.signs),
    ["no_direction", "opposite_signs", "opposite_signs", "same_sign", "not_covered", "not_covered"]);
  assert.equal(row(served, "2026-06").g17.marker, "p");
  assert.equal(served.sources!.eia.edition, null);
});

test("states other than checked carry no result", () => {
  const empty = { ...copy(), state: "not_checked", result: null, comparisons: null, periods: [], sources: null };
  assert.equal(isCrossSourceView(empty), true);
  assert.equal(isCrossSourceView({ ...empty, periods: served.periods }), false);
  assert.equal(isCrossSourceView({ ...copy(), provider_called: true }), false);
  assert.equal(isCrossSourceView({ ...copy(), view_version: "cross-source-view-0.0" }), false);
});

test("an EIA figure or sign label that does not follow from its values is refused", () => {
  const mutations: [string, (view: CrossSourceView) => void][] = [
    ["change", (view) => { row(view, "2024-Q4").eia.change = "7200.001"; }],
    ["percent", (view) => { row(view, "2024-Q4").eia.percent = "3.01"; }],
    ["sign", (view) => { row(view, "2024-Q4").eia.sign = -1; }],
    ["signs label", (view) => { row(view, "2024-Q4").signs = "same_sign"; }],
    ["not covered made computed", (view) => { row(view, "2026-07").signs = "opposite_signs"; }],
    ["printed rate", (view) => { row(view, "2024-Q4").g17.value = "-1.40"; }],
    ["G.17 sign", (view) => { row(view, "2024-Q4").g17.sign = 1; }],
    ["another release", (view) => { row(view, "2024-Q4").g17.sha256 = "b".repeat(64); }],
    ["another row", (view) => { row(view, "2024-Q4").g17.path = "INDUSTRY GROUP / Mining"; }],
    ["a month substituted", (view) => { view.periods[3].key = "2026-05"; }],
    ["an edition for the CSV", (view) => { (view.sources!.eia as { edition: unknown }).edition = "September 2026"; }],
  ];
  for (const [name, change] of mutations) {
    const view = copy();
    change(view);
    assert.equal(isCrossSourceView(view), false, name);
  }
});

test("the customer breakdown must add up exactly to the EIA total change", () => {
  const broken = copy();
  utility(broken, "2024-Q4").breakdown.sectors!.ESRCPUS = "3000.001";
  assert.equal(isCrossSourceView(broken), false);
  const total = copy();
  utility(total, "2024-Q4").breakdown.total_change = "1.000";
  assert.equal(isCrossSourceView(total), false);
  const classes = copy();
  utility(classes, "2024-Q4").eia_classes.ESCCPUS.change = "5999.000";
  assert.equal(isCrossSourceView(classes), false);
});

test("signs are sign-only, and a printed 0.0 has no direction", () => {
  assert.equal(rateSign(".0"), 0);
  assert.equal(rateSign("-.0"), 0);
  assert.equal(rateSign("-.5"), -1);
  assert.equal(rateSign("1.4"), 1);
  const june = row(served, "2026-06");
  assert.equal(expectedSigns(june.eia, { ...june.g17, value: ".0", sign: 0 }), "no_direction");
  assert.equal(expectedSigns({ ...june.eia, sign: 1 }, june.g17), "opposite_signs");
  assert.equal(eiaOk(row(served, "2023-Q4").eia, "ESICPUS"), true);
  assert.equal(eiaOk(row(served, "2023-Q4").eia, "ESTCPUS"), false);
});

test("the exact-decimal reader agrees with the electricity one", () => {
  for (const text of ["0", "-12.5", "1234.567", "-0.0025", ".7".replace(".", "0.")]) {
    assert.equal(units(text), electricityUnits(text));
  }
  assert.throws(() => units("1e3"));
});

test("printed G.17 rates keep their published form", () => {
  assert.equal(printed("1.4"), "+1.4%");
  assert.equal(printed("-1.4"), "−1.4%");
  assert.equal(printed(".7"), "+0.7%");
  assert.equal(printed(".0"), "0.0%");
  assert.equal(printed("-.0"), "−0.0%");
  assert.equal(printed(null), "blank");
});

test("the computation uses the insights header and never sends again after a lost reply", async () => {
  assert.equal(CROSS_SOURCE_INSIGHTS_HEADER, INSIGHTS_HEADER);
  const calls: RequestInit[] = [];
  globalThis.fetch = (async (_path: string, init: RequestInit) => {
    calls.push(init);
    throw new TypeError("connection lost");
  }) as typeof fetch;
  assert.equal((await runCrossSourceCheck()).state, "unconfirmed");
  assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(String(calls[0].body)), { check_cross_source: true });
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "not accepted" }), { status: 409 })) as
    typeof fetch;
  assert.deepEqual(await runCrossSourceCheck(), { state: "refused", message: "not accepted" });
});
