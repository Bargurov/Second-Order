// Research readiness: the page's reader accepts exactly the server's served replies (captured by
// tests/test_research_readiness.py) and refuses any reply whose parts disagree with each other.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { readable } from "../src/lifecycle.ts";
import { STATUS_LABEL, groupRows, isReadiness, readinessPath, type Readiness } from "../src/readiness.ts";

const load = (name: string): Readiness =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8")) as Readiness;
const accepted = (value: Readiness) => readable(value, isReadiness);

test("both served replies are read: the lifecycle version and every cross-check hold", () => {
  for (const name of ["research-readiness-ready.json", "research-readiness-not-ready.json"]) {
    assert.ok(accepted(load(name)), name);
  }
  const ready = load("research-readiness-ready.json");
  assert.deepEqual(ready.providers.map((item) => [item.provider, item.status]),
                   [["board-h15", "freeze_ready"], ["fred", "needs_baseline"]]);
  const notReady = load("research-readiness-not-ready.json");
  assert.ok(notReady.providers.every((item) => item.status === "needs_baseline" && item.baselines.length === 0));
  assert.match(notReady.answer.freeze_now, /^Nothing can be frozen prospectively for 2026-09-15 yet\./);
});

test("registry concepts are grouped apart and never shown as operational", () => {
  const { connected, concepts } = groupRows(load("research-readiness-ready.json").observables);
  assert.deepEqual(connected.map((row) => row.observable_id),
                   ["yield:ust2y_cmt", "yield:ust10y_cmt", "yield:ust2y_cmt_h15", "yield:ust10y_cmt_h15"]);
  assert.ok(concepts.some((row) => row.observable_id === "index:dxy"));
  assert.ok(concepts.some((row) => row.observable_id === "fx:usdils"));
  assert.ok(concepts.every((row) => row.status === "concept_only" && row.provider === null && !row.freeze.ready));
  assert.ok(concepts.every((row) => Object.keys(row.retained).length === 0));  // No fixture coverage is shown.
  assert.equal(STATUS_LABEL.concept_only, "Registry concept only");
});

test("the fictional demonstration series are reported apart and cover no registry concept", () => {
  const data = load("research-readiness-ready.json");
  const demo = data.demonstration!;
  assert.equal(data.provenance.fixture, "demo-market.json");
  assert.deepEqual([demo.fixture, demo.version, demo.registry_concepts_covered],
                   ["demo-market.json", "demo-market-0.1", []]);
  assert.deepEqual(demo.series.map((item) => [item.observable_id, item.provider]),
                   [["demo:rate", "fictional-demo"], ["demo:fx-index", "fictional-demo"]]);
  assert.ok(demo.series.every((item) => !data.observables.some((row) => row.observable_id === item.observable_id)));
  assert.match(demo.plain, /FICTIONAL demonstration series/);
});

test("a reply whose parts disagree is refused", () => {
  const cases: [string, (data: Readiness) => void][] = [
    ["a provider ready without a baseline", (data) => { data.providers[0].baselines = []; }],
    ["a provider baseline its observables cannot use", (data) => {  // The row itself stays consistent.
      const row = data.observables.find((item) => item.observable_id === "yield:ust10y_cmt_h15")!;
      row.status = "needs_baseline";
      row.freeze = { ready: false, baselines: [], scorable_horizons: [], blockers: ["Synthetic reason."] }; }],
    ["a ready row naming no baseline", (data) => {
      const row = data.observables.find((item) => item.observable_id === "yield:ust2y_cmt_h15")!;
      row.freeze.baselines = []; }],
    ["a registry concept with a provider", (data) => {
      const row = data.observables.find((item) => item.observable_id === "index:dxy")!;
      row.provider = { id: "fred", series_id: "X", name: "x", connection: "x", freeze_path: "x", outcome_path: "x" }; }],
    ["a registry concept marked ready", (data) => {
      const row = data.observables.find((item) => item.observable_id === "fx:usdils")!;
      row.status = "freeze_ready"; }],
    ["a row that is not ready without a reason", (data) => {
      data.observables.find((row) => row.observable_id === "yield:ust2y_cmt")!.freeze.blockers = []; }],
    ["a duplicated observable", (data) => { data.observables.push(data.observables[0]); }],
    ["an unknown status", (data) => { (data.observables[0] as { status: string }).status = "operational"; }],
    ["a provider with fewer than two observables", (data) => {
      data.observables = data.observables.filter((row) => row.observable_id !== "yield:ust10y_cmt"); }],
    ["a research observable that is not listed", (data) => { data.research.measurable_observables = ["index:spx"]; }],
    ["a demonstration series that covers a registry concept", (data) => {
      data.demonstration!.registry_concepts_covered = ["index:dxy"]; }],
    ["a demonstration series listed as a registry row", (data) => {
      data.demonstration!.series[0].observable_id = "index:dxy"; }],
    ["a required session on or after the publication date", (data) => { data.required_session = data.published_date; }],
    ["a provider call", (data) => { (data as { provider_called: boolean }).provider_called = true; }],
    ["a write", (data) => { (data as { written: boolean }).written = true; }],
    ["another readiness version", (data) => { data.readiness_version = "research-readiness-0.1"; }],
    ["a reply without the demonstration block", (data) => { delete (data as Partial<Readiness>).demonstration; }],
    ["another lifecycle version", (data) => { data.lifecycle_version = "lifecycle-freeze-0.2"; }],
    ["an empty answer", (data) => { data.answer.freeze_now = ""; }],
  ];
  for (const [label, change] of cases) {
    const data = structuredClone(load("research-readiness-ready.json"));
    change(data);
    assert.equal(accepted(data), false, label);
  }
});

test("the read names its publication date only when one is chosen", () => {
  assert.equal(readinessPath(null), "/api/lifecycle/readiness");
  assert.equal(readinessPath("2026-12-09"), "/api/lifecycle/readiness?published=2026-12-09");
});
