// The Method page documents implemented behavior. Its rules and labels are checked against output
// captured from the real preparation of a synthetic store (see tests/test_store_dossier.py).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { VERDICT_LABEL } from "../src/format.ts";
import {
  DOCUMENTED_RULES, DOSSIER_LABELS, LEG_LABELS, PROSPECTIVE_CLASS, SCORE_ANCHORS, TIMELINE_SCOPE, UNSCORED_INTERVAL,
  rulesStatus,
} from "../src/method.ts";
import type { Dossier, DossierIndex } from "../src/types.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8")) as T;

test("the documented rules are the rules recorded in real evaluations", () => {
  for (const name of ["store-evaluated.json", "store-pending.json"]) {
    assert.deepEqual(DOCUMENTED_RULES, load<Dossier>(name).evaluation?.rules, name);
  }
  assert.equal(load<DossierIndex>("index-pending.json").active_rules_version, DOCUMENTED_RULES.version);
});

test("every leg label the scorer can record is explained, once, in the scorer's order", () => {
  assert.deepEqual(LEG_LABELS.map((item) => item.verdict),
                   ["supported", "contradicted", "inconclusive", "unavailable", "excluded", "pending"]);
  assert.deepEqual(DOSSIER_LABELS.map((item) => item.verdict), ["mixed", "incomplete"]);
  for (const { verdict } of [...LEG_LABELS, ...DOSSIER_LABELS]) assert.ok(VERDICT_LABEL[verdict], verdict);
  const recorded = new Set([load<Dossier>("store-evaluated.json"), load<Dossier>("store-pending.json")]
    .flatMap((dossier) => dossier.evaluation?.legs.map((leg) => leg.verdict) ?? []));
  for (const verdict of recorded) assert.ok(LEG_LABELS.some((item) => item.verdict === verdict), verdict);
});

test("label meanings restate the rule's exact conditions", () => {
  const meaning = Object.fromEntries(LEG_LABELS.map((item) => [item.verdict, item.meaning]));
  assert.match(meaning.supported, /positive and its percentile rank is at least 0\.80/);
  assert.match(meaning.contradicted, /negative and its percentile rank is at most 0\.20/);
  assert.match(meaning.inconclusive, /extreme rank whose sign does not match/);
  assert.doesNotMatch(meaning.inconclusive, /ordinary|typical|no effect/i);
  assert.match(meaning.unavailable, /fewer than 120 usable reference windows/);
  assert.match(meaning.excluded, /headline already reports this measured move/);
  assert.match(meaning.pending, /incomplete when the evaluation ran/);
});

test("anchor copy never claims that every scored window starts after the freeze", () => {
  const anchor = (applies: string) => SCORE_ANCHORS.find((item) => item.applies === applies)?.anchor ?? "";
  // Equities frozen outside a session score from the preceding close, which can include extended hours.
  assert.match(anchor("Equities frozen outside a regular session"), /last regular-session close before the freeze/);
  assert.match(anchor("Equities frozen outside a regular session"), /precedes the freeze/);
  assert.match(anchor("Equities frozen outside a regular session"), /extended-hours trading already visible/);
  assert.match(anchor("Equities frozen during a regular session, its close included"), /first regular-session close after/);
  assert.match(anchor("Daily Treasury yields"), /first observation dated after the freeze date/);
  assert.match(anchor("Replays"), /the event anchor/);
  assert.match(PROSPECTIVE_CLASS, /For most observables the scored window starts after the freeze/);
  assert.match(PROSPECTIVE_CLASS, /outside a regular session is scored from the preceding close/);
  // The timeline is scoped to the cases it draws; the unscored interval is described case by case.
  assert.match(TIMELINE_SCOPE, /whose score anchor follows the freeze/);
  assert.doesNotMatch(TIMELINE_SCOPE, /outside a regular session|replay/i);
  assert.match(UNSCORED_INTERVAL, /When the score anchor follows the freeze, that interval holds the publication-day/);
  assert.match(UNSCORED_INTERVAL, /every replay/);
  assert.match(UNSCORED_INTERVAL, /the initial reaction is part of the scored move/);
  for (const text of [PROSPECTIVE_CLASS, TIMELINE_SCOPE, UNSCORED_INTERVAL, ...SCORE_ANCHORS.map((item) => item.anchor)]) {
    assert.doesNotMatch(text, /^Scoring starts after the freeze|every (prospective )?score anchor/i);
  }
  const pending = LEG_LABELS.find((item) => item.verdict === "pending")?.meaning ?? "";
  assert.doesNotMatch(pending, /no observation after the freeze/);
  assert.match(pending, /for daily yields, no observation dated after the freeze date/);
});

test("the rules note says when the active rules differ or are unknown", () => {
  assert.deepEqual(rulesStatus("0.5.0").matches, true);
  const other = rulesStatus("0.6.0");
  assert.equal(other.matches, false);
  assert.match(other.text, /documents rules 0\.5\.0, but the prepared index reports 0\.6\.0/);
  const unknown = rulesStatus(null);
  assert.equal(unknown.matches, null);
  assert.match(unknown.text, /not loaded/);
});
