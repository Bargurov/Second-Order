// What the Client says about who prepared a brief, a story's reporting origins and its relevance assessment, and how it
// reads a story's economic explanation (src/contracts/economics.ts), over the SYNTHETIC stories fixtures: labels come
// from each brief's own record, origins keep confirmed apart from possible, a missing assessment is never called a
// judgement, and an explanation that contradicts itself is refused rather than shown.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { economicsProblem, explanationProblem } from "../src/contracts/economics.ts";
import { readStory } from "../src/contracts/stories.ts";
import { briefTag, evidenceLine, figureDetails, originsLine, relevanceBasisLine } from "../src/client/storiesView.ts";

const fixtures = new URL("./fixtures/", import.meta.url);
const load = <T = Record<string, any>>(name: string): T =>
  JSON.parse(readFileSync(new URL(`${name}.json`, fixtures), "utf8"));
const counts = { publishers: 3, origins: 3, news_origins: 2, official_origins: 1, company_origins: 0,
  reporting_origins: 3, confirmed_news: 0, confirmed_official: 1, possible_news: 2, possible_official: 0, uncertain: 2,
  repeats: 0, company_statements: 0, official_releases: 1 };

test("the News introduction describes the workflow and claims no editor wrote the briefs", () => {
  const home = readFileSync(new URL("../src/client/components/NewsHome.tsx", import.meta.url), "utf8");
  const lede = /data-lede>([\s\S]*?)<\/p>/.exec(home)![1].replace(/\s+/g, " ");
  assert.doesNotMatch(lede, /our editors|editors prepare|editors write/i);
  assert.match(lede, /how it was prepared \(by an editor, or with AI\) and whether an editor has read it/);
  assert.match(home, /briefTag\(story\.brief\)/);
});

test("a card's brief label comes from the brief's own authorship and recorded review", () => {
  const card = (authorship: string | null, review: string | null, state = "published") =>
    ({ state, summary: state === "published" ? "x" : null, current: state === "published" ? true : null, authorship,
       review, explained: false }) as any;
  assert.equal(briefTag(card("ai_assistant", "not_reviewed")), "Brief · AI-assisted · not read by an editor");
  assert.equal(briefTag(card("ai_model", "read_by_editor")), "Brief · AI-drafted · read by an editor");
  assert.equal(briefTag(card("editor", "written_by_editor")), "Brief · Written by an editor");
  assert.equal(briefTag(card(null, null, "none")), "Awaiting a brief");
});

test("reporting origins keep confirmed apart from possible ones, in correct numbers", () => {
  assert.equal(originsLine(counts), "Reporting origins: 1 confirmed; 2 possible, independence not established · " +
    "3 publishers");
  assert.equal(originsLine({ ...counts, publishers: 1, origins: 1, news_origins: 0, reporting_origins: 1,
    possible_news: 0, uncertain: 0 }), "Reporting origins: 1 confirmed · 1 publisher");
  assert.equal(originsLine({ ...counts, publishers: 1, origins: 1, news_origins: 0, official_origins: 0,
    company_origins: 1, reporting_origins: 0, confirmed_official: 0, possible_news: 0, uncertain: 0,
    company_statements: 1 }), "Reporting origins: none: company statements only · 1 publisher");
  const page = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(page, /from \{page\.coverage\.publishers\} publishers/);
});

test("a story without a completed assessment never says it was judged", () => {
  assert.equal(relevanceBasisLine({ state: "pending", basis: null }), "No assessment has been made.");
  assert.equal(relevanceBasisLine({ state: "restricted", basis: null }), "No assessment has been made.");
  assert.match(relevanceBasisLine({ state: "unavailable", basis: "model" }), /^No assessment has been completed/);
  assert.match(relevanceBasisLine({ state: "relevant", basis: "assisted" }), /^A judgement made with AI/);
  assert.match(relevanceBasisLine({ state: "outside_scope", basis: "editor" }), /^An editor's judgement/);
  for (const state of ["pending", "restricted", "needs_review", "unavailable"]) {
    assert.doesNotMatch(relevanceBasisLine({ state: state as any, basis: null }), /judgement/);
  }
});

test("a story's economic explanation is read whole, with its parts kept apart", () => {
  const story = load("stories-contract-story").story;
  const economics = story.brief.economics;
  assert.equal(economics.status, "explained");
  const used = new Set<string>(story.brief.material.reports.map((row: any) => row.entry_id));
  assert.equal(economicsProblem(economics, used), null);
  assert.equal(readStory(load("stories-contract-story")).ok, true);
  assert.deepEqual(economics.channels.map((row: any) => row.kind), ["interpretation"]);
  assert.equal(economics.figures[0].kind, "reported");
  assert.equal(economics.notes[0].kind, "reasoning");
  assert.equal(story.explanation.state, "ready");
});

test("a figure says what kind of number it is, with the margin its quote writes, and nothing not stated", () => {
  const rate = { period: "September 2026", basis_label: null, seasonal_label: "seasonally adjusted",
    statistic_label: null, stock_flow_label: "a flow at an annual rate", margin: null };
  assert.deepEqual(figureDetails(rate), ["September 2026", "seasonally adjusted", "a flow at an annual rate"]);
  const change = { ...rate, stock_flow_label: null, basis_label: "nominal or real not stated", margin: "±13.8%" };
  assert.deepEqual(figureDetails(change), ["September 2026", "nominal or real not stated", "seasonally adjusted",
    "stated margin ±13.8%"]);
  assert.deepEqual(figureDetails({ ...rate, margin: undefined }), figureDetails(rate));  // Saved before 0.1.
  const story = load("stories-contract-story").story;
  const used = new Set<string>(story.brief.material.reports.map((row: any) => row.entry_id));
  const economics = structuredClone(story.brief.economics);
  economics.figures[0].margin = "±13.8%";
  assert.equal(economicsProblem(economics, used), null);
  economics.figures[0].margin = 13.8;
  assert.notEqual(economicsProblem(economics, used), null);  // A margin is shown as its quote writes it.
  const page = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  assert.match(page, /figureDetails\(row\)/);
});

test("what changed says the form of its evidence apart from its subject; an earlier one says it did not record it", () => {
  const story = load("stories-contract-story").story;
  const used = new Set<string>(story.brief.material.reports.map((row: any) => row.entry_id));
  const economics = structuredClone(story.brief.economics);
  assert.equal(economics.analysis_version, "econ-explanation-0.6");
  const saved04 = structuredClone(economics);  // An explanation saved under 0.4 reads as saved, and says its form.
  saved04.analysis_version = "econ-explanation-0.4";
  for (const row of saved04.alternatives) { delete row.support; delete row.support_label; delete row.assumptions; }
  assert.equal(economicsProblem(saved04, used), null);
  saved04.summary.form_label = null;
  assert.notEqual(economicsProblem(saved04, used), null);
  assert.deepEqual(evidenceLine(economics.summary), { recorded: true,
    text: "Evidence: an announced or adopted decision, proposal or measure. Subject: a tariff or duty on imports." });
  const banks = { ...economics.summary, instrument_label: "credit or financing conditions",  // SYNTHETIC survey.
    form_label: "respondents' answers in a survey", respondents_label: "banks" };
  assert.equal(evidenceLine(banks)!.text,
    "Evidence: respondents' answers in a survey (banks). Subject: credit or financing conditions.");
  const unstated = structuredClone(economics);
  unstated.summary.form_label = null;
  assert.notEqual(economicsProblem(unstated, used), null);  // A 0.4 explanation always says its form.
  const legacy = structuredClone(saved04);
  legacy.analysis_version = "econ-explanation-0.3";
  legacy.summary = { ...legacy.summary, instrument_label: "an official statistic", form_label: null,
    respondents_label: null, classification_note: "Classified as “an official statistic” before the form of evidence "
      + "was recorded apart from its subject: its evidence form and any survey respondents were not recorded." };
  assert.equal(economicsProblem(legacy, used), null);
  assert.deepEqual(evidenceLine(legacy.summary), { recorded: false, text: legacy.summary.classification_note });
  const older = structuredClone(legacy);
  older.analysis_version = "econ-explanation-0.2";
  for (const key of ["form_label", "respondents_label", "classification_note"]) delete older.summary[key];
  assert.equal(economicsProblem(older, used), null);  // Saved before either: read as it was.
  assert.equal(evidenceLine(older.summary), null);
  const net = "a net percentage: the share of respondents reporting one direction minus the share reporting the other";
  assert.deepEqual(figureDetails({ period: "Q3 2026", basis_label: null, seasonal_label: null, statistic_label: net,
    stock_flow_label: null, margin: null }), ["Q3 2026", net]);
  const page = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  assert.match(page, /data-evidence-form=/);
});

test("an explanation that contradicts itself is refused rather than shown", () => {
  const story = load("stories-contract-story").story;
  const good = story.brief.economics;
  const used = new Set<string>(story.brief.material.reports.map((row: any) => row.entry_id));
  const broken: [string, (value: any) => void][] = [
    ["no summary", (value) => { value.summary = null; }],
    ["no channel", (value) => { value.channels = []; }],
    ["an effect without a channel", (value) => { value.second_order = [{ ...value.second_order[0], from: "m9" }]; }],
    ["a report outside the material", (value) => { value.figures[0].reports = ["synthetic-ledger:00000000000000000000"]; }],
    ["an unrendered figure", (value) => { value.summary.why_it_matters = "a duty of {f1}"; }],
    ["insufficient yet explained", (value) => { value.status = "insufficient_evidence"; value.insufficient_reason = "x"; }],
    ["a note without a source", (value) => { value.notes[0].sources = []; }],
  ];
  for (const [why, change] of broken) {
    const value = structuredClone(good);
    change(value);
    assert.notEqual(economicsProblem(value, used), null, why);
  }
  assert.notEqual(explanationProblem({ state: "ready", statement: "x", reason: null }), null);
  assert.notEqual(explanationProblem({ state: "pending", statement: null, reason: null }), null);
  const pretends = load("stories-contract-story");
  pretends.story.brief.economics = null;
  assert.equal(readStory(pretends).ok, false);  // "ready" without an explanation.
});

test("an explanation saved under an earlier method reads as it was saved, and an unrecoverable background shows no notes", () => {
  const story = load("stories-contract-story").story;
  const used = new Set<string>(story.brief.material.reports.map((row: any) => row.entry_id));
  const current = story.brief.economics;
  assert.equal(current.analysis_version, "econ-explanation-0.6");
  assert.equal(current.background.state, "recorded");
  assert.equal(current.channels[0].support, "framework");
  const legacy = structuredClone(current);
  legacy.analysis_version = "econ-explanation-0.1";
  delete legacy.background;
  for (const row of legacy.channels) { delete row.support; delete row.support_label; }
  for (const row of legacy.alternatives) { delete row.support; delete row.support_label; delete row.assumptions; }
  assert.equal(economicsProblem(legacy, used), null);  // Published 0.1 explanations stay readable.
  const lost = structuredClone(current);
  lost.background = { state: "unavailable", framework_version: null, framework_sha256: null };
  assert.notEqual(economicsProblem(lost, used), null);  // Notes shown although the framework is unrecoverable.
  lost.notes = [];
  assert.equal(economicsProblem(lost, used), null);
  const page = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  assert.match(page, /data-background="unavailable"/);
  assert.match(page, /Supported by:/);
  assert.match(page, /data-explanation-note="outdated"/);
});

test("context says what it is for and when it was published, and the page says what was read beyond the material", () => {
  const page = load("stories-contract-story");
  const used = new Set<string>(page.story.brief.material.reports.map((row: any) => row.entry_id));
  const row = { item_id: "o1", kind: "observation", publisher: "SYNTHETIC statistics office release", title: null,
    link: "https://example.org/synthetic-release", published: "2026-10-20", as_of: "2026-10-20",
    attribution: "SYNTHETIC test item", role: "event_evidence", role_label: "Evidence on this development",
    relevance: "SYNTHETIC: the release's own statement.", retrieved: "2026-10-26", timing: "after",
    timing_label: "Published after this story was first reported.", retrospective: true };
  const economics = structuredClone(page.story.brief.economics);
  economics.context = [row];
  assert.equal(economicsProblem(economics, used), null);
  const unlabelled = { ...economics, context: [{ ...row, retrospective: false }] };  // Later context not marked.
  assert.notEqual(economicsProblem(unlabelled, used), null);
  assert.notEqual(economicsProblem({ ...economics, context: [{ ...row, role: "decoration" }] }, used), null);
  const legacy = { ...economics, context: [{ ...row, role: undefined, role_label: undefined, relevance: undefined,
    retrieved: undefined, timing: undefined, timing_label: undefined, retrospective: undefined }] };
  assert.equal(economicsProblem(legacy, used), null);  // A 0.1 bundle's item reads as it was saved.
  page.story.brief.economics = economics;
  page.story.brief.context_statement = null;
  assert.equal(readStory(page).ok, false);  // Context was read, and the page does not say so.
  page.story.brief.context_statement = "The economic explanation also draws on 1 quoted passage of SYNTHETIC " +
    "statistics office release (on this development).";
  assert.equal(readStory(page).ok, true);
  const view = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  assert.match(view, /data-context-statement/);
  assert.match(view, /Later context/);
  assert.match(view, /Why it is used:/);
});

test("an alternative says what supports it and what it assumes; an earlier one reads as it was saved", () => {
  const story = load("stories-contract-story").story;
  const used = new Set<string>(story.brief.material.reports.map((row: any) => row.entry_id));
  const economics = structuredClone(story.brief.economics);
  assert.equal(economics.analysis_version, "econ-explanation-0.6");
  assert.equal(economicsProblem(economics, used), null);
  const ids = economics.assumptions.map((row: any) => row.id);
  const broken: [string, (value: any) => void][] = [
    ["no support", (value) => { delete value.alternatives[0].support; }],
    ["a channel's support it cannot have", (value) => { value.alternatives[0].support = "framework"; }],
    ["an inference resting on no assumption", (value) => {
      value.alternatives[0].support = "bounded_inference"; value.alternatives[0].assumptions = []; }],
    ["an assumption the explanation does not state", (value) => {
      value.alternatives[0].support = "bounded_inference"; value.alternatives[0].assumptions = ["a9"]; }],
    ["no label for its support", (value) => { value.alternatives[0].support_label = ""; }],
  ];
  for (const [why, change] of broken) {
    const value = structuredClone(economics);
    change(value);
    assert.notEqual(economicsProblem(value, used), null, why);
  }
  const inference = structuredClone(economics);
  inference.alternatives[0] = { ...inference.alternatives[0], support: "bounded_inference",
    support_label: "An inference resting on stated assumptions", assumptions: [ids[0]] };
  assert.equal(economicsProblem(inference, used), null);
  const earlier = structuredClone(economics);  // Saved under 0.5: its alternatives record no support.
  earlier.analysis_version = "econ-explanation-0.5";
  for (const row of earlier.alternatives) { delete row.support; delete row.support_label; delete row.assumptions; }
  assert.equal(economicsProblem(earlier, used), null);
  earlier.alternatives[0].support = "event_evidence";
  assert.notEqual(economicsProblem(earlier, used), null);  // An earlier explanation never gains a support it lacked.
  const page = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  assert.match(page, /assumed\(row\.assumptions \?\? \[\]\)/);
  assert.match(page.replace(/\s+/g, " "), /data-steps-note>Each step could follow from the one before; the steps are not a timeline/);
});
