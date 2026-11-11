// Tracker logic, read from indexes captured from the real preparation of a synthetic store
// (see tests/test_store_dossier.py): two fixture replays of fictional events and one prospective case.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { VIEW_VERSION } from "../src/api.ts";
import { joinLegs } from "../src/join.ts";
import { evaluationStatus, trackerSections, usageLabel } from "../src/tracker.ts";
import type { Dossier, DossierIndex } from "../src/types.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8")) as T;
const frozen = () => load<DossierIndex>("index-not-evaluated.json");
const pending = () => load<DossierIndex>("index-pending.json");

test("the captured indexes carry the version this client reads", () => {
  assert.equal(frozen().view_version, VIEW_VERSION);
  assert.equal(pending().view_version, VIEW_VERSION);
});

test("prospective cases and retrospective replays are separated, newest first", () => {
  const sections = trackerSections(frozen());
  assert.deepEqual(sections.prospective.map((row) => row.evidence_class), ["prospective"]);
  assert.deepEqual(sections.replay.map((row) => row.published_at), ["2024-10-30T18:00:00Z", "2024-06-12T18:00:00Z"]);
  assert.equal(sections.researchCases, 0);
  assert.deepEqual([...sections.prospective, ...sections.replay].map((row) => usageLabel(row.usage)),
                   ["Showcase", "Showcase", "Showcase"]);
});

test("not yet evaluated and an evaluated pending result are different states", () => {
  const before = evaluationStatus(trackerSections(frozen()).prospective[0]);
  const after = evaluationStatus(trackerSections(pending()).prospective[0]);
  assert.deepEqual(before, { kind: "not_evaluated", label: "Not yet evaluated", className: "state-unevaluated",
                             detail: "No evaluation has been recorded." });
  assert.equal(after.kind, "recorded");
  assert.equal(after.label, "Pending");
  assert.equal(after.className, "verdict-pending");
  assert.equal(after.detail, "Evaluation recorded as of 22 Jun 2025, 12:00 UTC, rules 0.5.0. The scored window was " +
                             "incomplete at that evaluation, so its result is pending.");
  assert.notEqual(before.label, after.label);
});

test("recorded verdicts show their evaluation clock and rules", () => {
  const [october, june] = trackerSections(frozen()).replay.map(evaluationStatus);
  assert.deepEqual([october.label, june.label], ["Contradicted", "Supported"]);
  assert.equal(june.detail, "Evaluation recorded as of 31 Dec 2024, 23:59 UTC, rules 0.5.0.");
});

test("a contradictory index row is shown as inconsistent, never as a result", () => {
  const row = { ...trackerSections(frozen()).prospective[0], state: "evaluated" as const };
  assert.equal(evaluationStatus(row).kind, "inconsistent");
  const orphan = { ...trackerSections(pending()).prospective[0], state: "not_evaluated" as const };
  assert.equal(evaluationStatus(orphan).kind, "inconsistent");
});

test("research rows are labelled and counted, and an empty index has empty sections", () => {
  const index = frozen();
  index.dossiers[0] = { ...index.dossiers[0], usage: "research" };
  assert.equal(trackerSections(index).researchCases, 1);
  assert.equal(usageLabel("research"), "Research");
  const empty = trackerSections({ ...frozen(), dossiers: [] });
  assert.deepEqual([empty.prospective.length, empty.replay.length, empty.researchCases], [0, 0, 0]);
});

test("the pending Dossier joins: anchors recorded, nothing ranked for the pending leg", () => {
  const dossier = load<Dossier>("store-pending.json");
  const legs = joinLegs(dossier);
  assert.ok(legs);
  const primary = legs.find((leg) => leg.definition.primary);
  assert.equal(primary?.result?.verdict, "pending");
  assert.equal(primary?.view.reference, null);
  assert.equal(primary?.view.anchor_dates?.target_at, undefined);
});
