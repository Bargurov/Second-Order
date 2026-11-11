// What the Client says about a recorded analysis's research checks (src/client/checksView.ts), against the canonical
// SYNTHETIC quality fixtures read by the contract's own reader: names and rules come from the payload (so a new rubric
// version needs no change here), each finding points to its place in the result, and nothing is said as a score, a
// pass mark, an approval or a confirmation. A flag can be wrong and a mistake can go unflagged; the copy says so with
// or without findings. Page rules only; which checks fire on which mistakes is the data owner's regression suite.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { QUALITY_VERSION, readQuality, type Quality } from "../src/contracts/news.ts";
import {
  CHECKS_LIMITS, CHECKS_READ, NO_CHECKS, NOTHING_FLAGGED, checkName, checksRun, findingsShown, locationOf,
} from "../src/client/checksView.ts";

const quality = (name: string): Quality | null => {
  const read = readQuality(JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8")));
  assert.ok(read.ok, `${name}: ${read.ok ? "" : read.problem}`);
  return read.value.quality;
};
const flagged = quality("news-contract-quality-flagged")!;
const clean = quality("news-contract-quality")!;
// Client wording only (the server's own sentences are shown as they are): no verdict of any kind.
const VERDICT = /\bscore|\bgrade|\bpass(?:ed|es|ing)?\b|pass mark|\bapprov|\bverified\b|\bcertif|\baccurate\b|\d+\s?%|\bconfidence\b/i;
const ADMIN_ONLY = /claude|sonnet|opus|haiku|anthropic|openai|\$\s?\d|\busd\b|\btokens?\b|\bcosts?\b|\bproviders?\b|\bmodels?\b|\busage\b/i;

test("the canonical fixtures are read under the current contract: one flagged finding, none, and no analysis", () => {
  assert.equal(flagged.rubric_version, QUALITY_VERSION);
  assert.equal(QUALITY_VERSION, "research-quality-0.3");
  assert.equal(flagged.flagged, 1);
  assert.equal(clean.flagged, 0);
  assert.deepEqual(clean.findings, []);
  assert.equal(quality("news-contract-quality-none"), null);
});

test("every check run is named from the payload, in its order, with its rule; none is listed from memory", () => {
  const run = checksRun(flagged);
  assert.equal(run.length, Object.keys(flagged.checks).length);
  assert.deepEqual(run.map((check) => check.rule), Object.values(flagged.checks));
  // research-quality-0.3's own additions are there because the payload names them.
  for (const name of ["Level change differs", "Negation differs", "Speaker differs", "Number not in source"]) {
    assert.ok(run.some((check) => check.name === name), name);
  }
  const later = checksRun({ ...flagged, checks: { ...flagged.checks, a_later_check: "SYNTHETIC rule of a later version." } });
  assert.deepEqual(later.at(-1), { name: "A later check", rule: "SYNTHETIC rule of a later version." });
});

test("a finding shows its place in the result, the server's detail and its rule", () => {
  const [finding] = findingsShown(flagged);
  assert.equal(finding.name, "Number not in source");
  assert.deepEqual(finding.place, { label: "Statement 1", anchor: "#statement-1" });
  assert.equal(finding.detail, flagged.findings[0].detail);
  assert.equal(finding.rule, flagged.checks[finding.check]);
  assert.deepEqual(findingsShown(clean), []);
});

test("each kind of place is said in the result's own terms; an unknown one is shown as written, never hidden", () => {
  assert.deepEqual(locationOf("established[12]"), { label: "Statement 12", anchor: "#statement-12" });
  assert.deepEqual(locationOf("missing_information[2]"), { label: "Missing information, item 2", anchor: null });
  assert.deepEqual(locationOf("interpretation"), { label: "The interpretation", anchor: null });
  assert.deepEqual(locationOf("analysis"), { label: "The analysis as a whole", anchor: null });
  assert.deepEqual(locationOf("source"), { label: "The source text", anchor: null });
  assert.deepEqual(locationOf("assumptions[1]"), { label: "assumptions[1]", anchor: null });
  assert.equal(checkName("number_not_in_quotes"), "Number not in quotes");
});

test("with findings or without, the limits are said: a flag can be wrong, a mistake can go unflagged", () => {
  assert.match(CHECKS_LIMITS, /A flag can be wrong, and a mistake can go unflagged/);
  assert.match(NOTHING_FLAGGED, /not a confirmation that the analysis is correct/);
  assert.match(clean.statement, /no flag is not a confirmation/);  // The server says it too; both are shown.
  assert.ok(flagged.human_review.length > 0 && clean.human_review.length === flagged.human_review.length);
  assert.match(CHECKS_READ, /contacts no publisher, runs no analysis and uses no credits/);
});

test("the Client's own words give no score, pass mark, approval or confirmation, and no administrator's vocabulary", () => {
  const said = [CHECKS_LIMITS, NOTHING_FLAGGED, NO_CHECKS, CHECKS_READ, "Checks to examine",
    "Flagged for you to look at", "For you to judge, whatever the checks say",
    ...checksRun(flagged).map((check) => check.name), ...findingsShown(flagged).map((finding) => finding.place.label)];
  for (const text of said) {
    assert.doesNotMatch(text, VERDICT, text);
    assert.doesNotMatch(text, ADMIN_ONLY, text);
  }
});
