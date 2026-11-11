// Electricity findings client logic, against the view the backend serves for the SYNTHETIC scenario (captured by
// tests/test_electricity.py into fixtures/electricity-view.json): read fail-closed, every number cross-checked, the
// CSV never given an edition, formatting exact, and a lost check reply never sent again.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, test } from "node:test";
import {
  ELECTRICITY_INSIGHTS_HEADER, ELECTRICITY_VIEW_VERSION, comparisonOk, isElectricityView, level, percent,
  runElectricityCheck, signed, units, type Comparison, type ElectricityView,
} from "../src/electricity.ts";
import { INSIGHTS_HEADER } from "../src/insights.ts";

const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; });
const served: ElectricityView = JSON.parse(readFileSync(new URL("./fixtures/electricity-view.json", import.meta.url),
  "utf8"));
const copy = (): ElectricityView => structuredClone(served);

test("the served view is read, with the scenario's findings", () => {
  assert.equal(served.view_version, ELECTRICITY_VIEW_VERSION);
  assert.equal(isElectricityView(served), true);
  assert.equal(served.months.length, 12);
  assert.deepEqual(served.findings!.monthly.map((card) => card.key),
    ["2026-06", "2026-05", "2026-04", "2026-03", "2026-02", "2026-01", "2025-08", "2025-07"]);
  assert.ok(served.findings!.period);
  assert.equal(served.sources.find((source) => source.kind === "csv")!.edition, null);
});

test("states other than checked carry no result", () => {
  const empty = { ...copy(), state: "not_checked", result: null, findings: null, months: [], period: null,
    coverage: null, reconciliation: null };
  assert.equal(isElectricityView(empty), true);
  assert.equal(isElectricityView({ ...empty, months: served.months }), false);
  assert.equal(isElectricityView({ ...copy(), provider_called: true }), false);
  assert.equal(isElectricityView({ ...copy(), written: true }), false);
  assert.equal(isElectricityView({ ...copy(), view_version: "electricity-view-0.0" }), false);
});

test("a class, change or percentage that does not follow from the values is refused", () => {
  const mutations: [string, (view: ElectricityView) => void][] = [
    ["class", (view) => { view.months[1].sectors[0].class = "little_changed"; }],
    ["percent", (view) => { view.months[1].sectors[0].percent = "1.01"; }],
    ["change", (view) => { view.months[1].sectors[0].change = "1000.001"; }],
    ["prior", (view) => { view.months[1].sectors[0].prior = "99999.000"; }],
    ["context class", (view) => { view.months[0].context[1].class = "down"; }],
    ["divergence list", (view) => { view.months[0].divergence.down = []; }],
    ["divergence flag", (view) => { view.months[2].divergence.finding = true; }],
  ];
  for (const [name, change] of mutations) {
    const view = copy();
    change(view);
    assert.equal(isElectricityView(view), false, name);
  }
});

test("months must be the twelve consecutive months of the scope, each against a year earlier", () => {
  const swapped = copy();
  [swapped.months[0], swapped.months[1]] = [swapped.months[1], swapped.months[0]];
  assert.equal(isElectricityView(swapped), false);
  const short = copy();
  short.months.pop();
  assert.equal(isElectricityView(short), false);
  const prior = copy();
  prior.months[3].prior = "2024-09";
  assert.equal(isElectricityView(prior), false);
  const reordered = copy();
  reordered.months[0].sectors.reverse();
  assert.equal(isElectricityView(reordered), false);
});

test("cards must match their months, carry the six disclosures and cite the CSV", () => {
  const extra = copy();
  extra.findings!.monthly.push({ ...extra.findings!.monthly[0], key: "2025-09" });
  assert.equal(isElectricityView(extra), false);
  const quiet = copy();
  quiet.findings!.monthly[0].disclosures = quiet.findings!.monthly[0].disclosures.slice(1);
  assert.equal(isElectricityView(quiet), false);
  const source = copy();
  source.findings!.monthly[0].source.sha256 = "b".repeat(64);
  assert.equal(isElectricityView(source), false);
  const edited = copy();
  edited.findings!.monthly[0].observed[0].current = "1.000";
  assert.equal(isElectricityView(edited), false);
  const nowhere = copy();
  nowhere.findings!.period = null;
  assert.equal(isElectricityView(nowhere), false);
  const count = copy();
  count.findings!.total = 1;
  assert.equal(isElectricityView(count), false);
});

test("the CSV is never given an edition", () => {
  const view = copy();
  view.sources.find((source) => source.kind === "csv")!.edition = "September 2026";
  assert.equal(isElectricityView(view), false);
});

test("contributions must add up exactly to the total change, which the total's comparison shows", () => {
  const broken = copy();
  broken.months[0].contributions.rows![0].change = "1.000";
  assert.equal(isElectricityView(broken), false);
  const residual = copy();
  residual.months[0].contributions.residual_change = "0.001";
  assert.equal(isElectricityView(residual), false);
  const total = copy();
  total.period!.contributions.total_change = "0.000";
  assert.equal(isElectricityView(total), false);
  const reconciliation = copy();
  reconciliation.reconciliation!.months[0].residual = "0.002";
  assert.equal(isElectricityView(reconciliation), false);
});

test("the ±1% bounds are inclusive and decided on exact values", () => {
  const item = (current: string, prior: string, cls: Comparison["class"], shown: string): Comparison => ({
    code: "ESRCPUS", key: "residential", label: "Residential", role: "analyzed", current, prior,
    change: (Number(units(current) - units(prior)) / 10_000).toFixed(3), percent: shown, class: cls, reason: null });
  assert.equal(comparisonOk(item("101000.000", "100000.000", "up", "1.00")), true);
  assert.equal(comparisonOk(item("100999.999", "100000.000", "little_changed", "0.99")), true);
  assert.equal(comparisonOk(item("100999.999", "100000.000", "up", "0.99")), false);
  assert.equal(comparisonOk(item("99000.000", "100000.000", "down", "-1.00")), true);
  assert.equal(comparisonOk(item("99000.001", "100000.000", "little_changed", "-0.99")), true);
  assert.equal(comparisonOk({ ...item("1.000", "0.000", "unavailable", "0.00"), change: null, percent: null,
    reason: "the prior value 0.000 is not a positive denominator" }), true);
});

test("numbers are shown exactly, with signs and thousands separators", () => {
  assert.equal(units("-12.5"), -125000n);
  assert.throws(() => units("1e3"));
  assert.equal(level("1234567.891"), "1,234,567.891");
  assert.equal(level("-800.000"), "−800.000");
  assert.equal(signed("1000.000"), "+1,000.000");
  assert.equal(signed("-0.002"), "−0.002");
  assert.equal(signed("0.000"), "0.000");
  assert.equal(percent("1.00"), "+1.00%");
  assert.equal(percent("-2.45"), "−2.45%");
  assert.equal(percent("0.00"), "0.00%");
  assert.equal(percent(null), "not available");
});

test("the check uses the insights header and never sends again after a lost reply", async () => {
  assert.equal(ELECTRICITY_INSIGHTS_HEADER, INSIGHTS_HEADER);
  const calls: RequestInit[] = [];
  globalThis.fetch = (async (_path: string, init: RequestInit) => {
    calls.push(init);
    throw new TypeError("connection lost");
  }) as typeof fetch;
  const lost = await runElectricityCheck();
  assert.equal(lost.state, "unconfirmed");
  assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(String(calls[0].body)), { check_retained_electricity: true });
  assert.equal((calls[0].headers as Record<string, string>)[ELECTRICITY_INSIGHTS_HEADER], "1");
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "No retained files" }),
    { status: 409 })) as typeof fetch;
  assert.deepEqual(await runElectricityCheck(), { state: "refused", message: "No retained files" });
  globalThis.fetch = (async () => new Response(JSON.stringify({ view_version: ELECTRICITY_VIEW_VERSION,
    result_id: "c".repeat(64), created: true, months: 12, monthly_findings: 8, period_finding: true,
    provider_called: false }), { status: 201 })) as typeof fetch;
  assert.equal((await runElectricityCheck()).state, "done");
});
