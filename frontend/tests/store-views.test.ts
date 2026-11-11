// Store-backed views, read from views captured from the real preparation (see tests/test_store_dossier.py).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { VIEW_VERSION } from "../src/api.ts";
import { NOT_EVALUATED, anchorDay, anchorPoints, authorshipNote, caseStatus, formatDay } from "../src/format.ts";
import { joinLegs } from "../src/join.ts";
import type { Dossier } from "../src/types.ts";

const load = (name: string): Dossier =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8")) as Dossier;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

test("the captured views carry the version this client reads", () => {
  for (const name of ["store-not-evaluated.json", "store-evaluated.json"]) assert.equal(load(name).view_version, VIEW_VERSION);
});

test("a frozen case before evaluation joins with no results and nothing drawn", () => {
  const dossier = load("store-not-evaluated.json");
  const legs = joinLegs(dossier);
  assert.ok(legs);
  assert.equal(legs.length, 2);
  for (const leg of legs) {
    assert.equal(leg.result, null);
    assert.equal(leg.view.series, null);
    assert.equal(leg.view.reference, null);
  }
  assert.deepEqual(caseStatus({ state: dossier.state, verdict: null }), { label: NOT_EVALUATED, className: "state-unevaluated" });
  assert.equal(dossier.data_provenance?.outcome, null);
  assert.match(dossier.data_provenance?.attribution ?? "", /FRED® API/);
  assert.equal(
    authorshipNote(dossier.hypothesis),
    "Submitted manually and frozen before its outcome; not a run of the project's model adapter, which does not " +
      "rule out AI assistance. Not research evidence.",
  );
  const manual = dossier.limitations.find((item) => item.title === "Manual submission");
  assert.match(manual?.text ?? "", /outside the project's model adapter, which does not rule out AI assistance/);
});

test("a daily FRED series is drawn and labelled by New York observation date", () => {
  const dossier = load("store-evaluated.json");
  const legs = joinLegs(dossier);
  assert.ok(legs);
  for (const leg of legs) {
    assert.ok(leg.result && leg.view.series);
    assert.equal(leg.view.series.time_basis, "daily_date");
    assert.ok(leg.view.series.points.every(([day]) => DATE.test(day)));
    assert.match(leg.view.series.attribution ?? "", /FRED® API/);
    const anchors = anchorPoints(leg.result, leg.view);
    const days = new Set(leg.view.series.points.map(([day]) => day));
    for (const key of ["event_anchor", "score_anchor", "target_at"] as const) assert.ok(days.has(anchors[key] ?? ""), key);
  }
  const primary = legs.find((leg) => leg.definition.primary);
  assert.ok(primary?.result);
  const anchors = anchorPoints(primary.result, primary.view);
  // The recorded instant is 23:59:59 New York, which is already the next day in UTC.
  assert.equal(primary.result.event_anchor, "2025-05-31T03:59:59+00:00");
  assert.equal(formatDay(primary.result.event_anchor), "31 May 2025");
  assert.equal(anchorDay(anchors, "event_anchor"), "30 May 2025");
  assert.equal(anchorDay(anchors, "target_at"), "11 Jun 2025");
  assert.equal(dossier.published_date, "2025-06-03");
});

test("an inconsistent prepared view is refused rather than repaired", () => {
  const evaluated = load("store-evaluated.json");
  const frozen = load("store-not-evaluated.json");
  const drawnBeforeEvaluation = { ...frozen, legs: frozen.legs.map((leg, i) => ({ ...leg, series: evaluated.legs[i].series })) };
  const stateMismatch = { ...evaluated, state: "not_evaluated" as const };
  const missingAnchorDates = { ...evaluated, legs: evaluated.legs.map((leg) => ({ ...leg, anchor_dates: null })) };
  const missingResult = { ...evaluated, evaluation: evaluated.evaluation && { ...evaluated.evaluation, legs: evaluated.evaluation.legs.slice(1) } };
  for (const dossier of [drawnBeforeEvaluation, stateMismatch, missingAnchorDates, missingResult]) {
    assert.equal(joinLegs(dossier), null);
  }
});

test("index status never invents a verdict", () => {
  assert.deepEqual(caseStatus({ state: "evaluated", verdict: "contradicted" }), {
    label: "Contradicted",
    className: "verdict-contradicted",
  });
  assert.equal(caseStatus({ state: "not_evaluated", verdict: null }).label, NOT_EVALUATED);
  assert.equal(caseStatus({ state: "evaluated", verdict: null }).label, NOT_EVALUATED);
});
