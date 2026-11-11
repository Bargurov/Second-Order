// The metals page's research-section helpers (metalsSections.ts) against replies captured from the server
// (tests/fixtures/metals-*.json): each picks what the reply holds, or writes a shown figure in the page's words; none
// computes a figure, and a withheld part gives its problem, never a value.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { Chapter, MetalsView } from "../src/metals.ts";
import {
  concentrationRows, coverageText, FINAL_PRODUCTS, hhiText, importCoverageText, ladder, leaderPair, linkCounts,
  linkIndicators, missingStage, NO_EVENT, partsFor, passagePlace, relianceCount, relianceOneOf, relianceText, riskOf,
  splitEvents, stageOfSeries, verified,
} from "../src/metalsSections.ts";
import { reservesOf, type CitedPassage, type MeasuredLink, type RiskChapter } from "../src/metalsStage2.ts";

const fixture = (name: string): MetalsView =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));
const view = fixture("metals-view.json");
const risk = (id: string, body: MetalsView = view) => riskOf(body, id) as RiskChapter;
const chapter = (id: string, body: MetalsView = view) => (body.usgs.chapters as Chapter[]).find((item) => item.id === id)!;

test("an HHI is written with both bounds, grouped, or as one number when they are equal", () => {
  assert.equal(hhiText("1037", "1206"), "1,037–1,206");
  assert.equal(hhiText("6100", "6100"), "6,100");
  assert.equal(hhiText("737", "4657"), "737–4,657");
  assert.equal(hhiText("10000", "10000"), "10,000");
  assert.equal(hhiText("526", "526"), "526");
});

test("coverage is written beside the HHI, and says when the named countries pass the printed total", () => {
  assert.equal(coverageText("87.0", false), "named countries 87.0% of the world total");
  assert.equal(coverageText("110.0", true), "named countries 110.0%, over the printed total");
  assert.equal(coverageText("50.0", null), "named countries 50.0% of the world total");
  assert.equal(importCoverageText("94.0"), "named sources 94.0% of US imports");
});

test("US reliance keeps its print: a number gets its percent sign, a code or a bound does not", () => {
  assert.equal(relianceText("57"), "57%");
  assert.equal(relianceText("1,200"), "1,200%");
  assert.equal(relianceText(">50"), ">50");
  assert.equal(relianceText("E"), "E");
  assert.equal(relianceText("W"), "W");
  assert.equal(relianceText("<25"), "<25");
});

test("a chapter printing more than one 2025 reliance figure is counted, so each figure can be named", () => {
  assert.equal(relianceCount(chapter("titanium-and-titanium-dioxide")), 2);
  assert.equal(relianceCount(chapter("rare-earths")), 1);  // Its 2024 row is not counted.
  assert.equal(relianceCount(chapter("cobalt")), 0);
  assert.equal(relianceOneOf(2), "One of 2 2025 figures USGS prints for this chapter");
});

test("a passage is placed by its source's title, publisher and edition, never its id or edition date", () => {
  const evidence = { id: "fcx-ptfi-2026", source: "sec-fcx-2025", title: "Annual report on Form 10-K for fiscal 2025",
    publisher: "Freeport-McMoRan Inc.", edition: "Fiscal 2025", edition_date: "2026-02-13", quote: "A quote.",
    where: "page 45", state: "verified" as const, problem: null };
  assert.equal(passagePlace(evidence),
    "Annual report on Form 10-K for fiscal 2025 · Freeport-McMoRan Inc., Fiscal 2025 · page 45");
  assert.equal(passagePlace({ ...evidence, source: null, title: null, publisher: null, edition: null, edition_date: null,
    where: null, quote: null, state: "unavailable", problem: "The copper thesis cannot be read" }), null);
});

test("the fixed words of the supply chain and events", () => {
  assert.equal(missingStage("refining"), "USGS's file has no refining table for this metal");
  assert.equal(missingStage("mining"), "USGS's file has no mining table for this metal");
  assert.equal(FINAL_PRODUCTS, "Final products: no retained source covers this stage.");
  assert.equal(NO_EVENT, "No verified event is retained for this metal. Events appear here only from a retained "
    + "primary source (an official publication or a filing), dated.");
});

test("each part is shown for a metal over a full reply; research is null for a metal with no notes", () => {
  const copper = partsFor(view, "copper");
  assert.ok(copper.risk.shown && copper.risk.value.id === "copper");
  assert.ok(copper.uses.shown && copper.uses.value.map((entry) => entry.name).join() === "Copper");
  assert.ok(copper.research.shown && copper.research.value?.thesis === "copper");
  assert.match(copper.writtenBy, /^Written by the assistant/);
  const rare = partsFor(view, "rare-earths");
  assert.ok(rare.uses.shown);
  assert.deepEqual(rare.uses.value.map((entry) => entry.name), ["Neodymium", "Total rare earth elements"]);
  const gold = partsFor(view, "gold");
  assert.ok(gold.uses.shown && gold.uses.value.length === 0);
  assert.ok(gold.research.shown && gold.research.value === null);
});

test("a withheld part gives its own problem and no value, whichever part it is", () => {
  const usgs = fixture("metals-usgs-changed.json");
  const parts = partsFor(usgs, "copper");
  assert.ok(!parts.risk.shown);
  assert.equal(parts.risk.problem, usgs.risk.problem);
  assert.equal(riskOf(usgs, "copper"), null);
  assert.ok(parts.uses.shown && parts.research.shown);
  const iea = partsFor(fixture("metals-iea-changed.json"), "copper");
  assert.ok(iea.risk.shown && !iea.uses.shown);
  assert.match(iea.uses.shown ? "" : iea.uses.problem, /differs from its acquisition record/);
  const both = fixture("metals-unavailable.json");
  const none = partsFor(both, "cobalt");
  assert.ok(!none.risk.shown && !none.uses.shown && none.research.shown);
  const research = partsFor({ ...view, research: { ...view.research, state: "withheld",
    problem: "The research notes are not in the shape this version reads", metals: {} } }, "copper");
  assert.ok(!research.research.shown);
  assert.equal(research.research.problem, "The research notes are not in the shape this version reads");
  assert.equal(research.writtenBy, view.research.written_by);
});

test("the ladder names a missing stage in its place and never fills it from another", () => {
  const cobalt = ladder(risk("cobalt"));
  assert.deepEqual(cobalt.map((step) => step.kind === "stage" ? step.stage.detail : `missing ${step.stage}`),
    ["Mine production", "missing refining"]);
  const copper = ladder(risk("copper"));
  assert.deepEqual(copper.map((step) => step.kind === "stage" ? step.stage.stage : "missing"), ["mining", "refining"]);
  const lithium = ladder(risk("lithium"));
  assert.deepEqual(lithium, [{ kind: "missing", stage: "mining" }, { kind: "missing", stage: "refining" }]);
  // A stage USGS prints under another name keeps its place after mining and refining.
  const made: RiskChapter = { ...risk("copper"), stages: [
    { ...risk("copper").stages[1], stage: "other", detail: "Primary production" }, risk("copper").stages[0]],
  missing_stages: ["refining"] };
  assert.deepEqual(ladder(made).map((step) => step.kind === "stage" ? step.stage.detail : `missing ${step.stage}`),
    ["Mine production", "missing refining", "Primary production"]);
});

test("the leader pair is the first mining and refining stage with a leader, as leaders_differ compares them", () => {
  const pair = leaderPair(risk("copper"));
  assert.equal(pair?.mining.leader.countries[0], "Chile");
  assert.equal(pair?.refining.leader.countries[0], "China");
  assert.equal(risk("copper").leaders_differ, true);
  assert.equal(leaderPair(risk("cobalt")), null);
  assert.equal(risk("cobalt").leaders_differ, null);
});

test("the stage with the largest single-country share is found by its series id; a reserves id has no stage", () => {
  const copper = risk("copper");
  assert.equal(stageOfSeries(copper, copper.most_concentrated)?.detail, "Refinery production");
  assert.equal(stageOfSeries(copper, "copper/reserves/reserves/metric-tons/2025"), null);
  assert.equal(stageOfSeries(copper, null), null);
});

test("concentration rows follow the indicators' order, each with its series and stage", () => {
  const rows = concentrationRows(chapter("copper"), risk("copper"));
  assert.deepEqual(rows.map((row) => [row.series.statistic, row.series.detail, row.stage?.stage ?? null]), [
    ["Production", "Mine production", "mining"], ["Reserves", "Reserves", null],
    ["Production", "Refinery production", "refining"]]);
  assert.equal(rows[0].indicators.hhi_low, "737");
  assert.equal(rows[0].series.leader.shown, "23.0");
  assert.deepEqual(concentrationRows(chapter("lithium"), risk("lithium")), []);
});

test("the snapshot's reserves are the series the research's reserves links read", () => {
  const [series, years] = reservesOf(chapter("copper"), risk("copper"));
  assert.equal(series?.id, "copper/reserves/reserves/metric-tons/2025");
  assert.equal(years?.production, "copper/production/mine-production/metric-tons/2025");
  const [none] = reservesOf(chapter("lithium"), risk("lithium"));
  assert.equal(none, null);
});

const passage = (id: string, state: CitedPassage["evidence"]["state"]): CitedPassage => ({
  passage: `copper:${id}`, evidence: state === "verified"
    ? { id, source: "usgs-2026", quote: "A quoted sentence.", where: "page 1", state, problem: null }
    : { id, source: "usgs-2026", quote: null, where: "page 1", state, problem: "The passage differs from its source" } });

test("a chain's links are counted by kind; a stated link whose quote is withheld is counted apart", () => {
  // The synthetic copper thesis cannot be read, so all three stated links have their quotes withheld.
  const links = view.research.metals.copper.chains[0].links;
  assert.deepEqual(linkCounts(links), { measured: 3, stated: 0, withheld: 3, hypothesis: 2 });
  const shown = links.map((link) => link.kind === "stated" ? { ...link, ...passage("p", "verified"), unavailable: null }
    : link);
  assert.deepEqual(linkCounts(shown), { measured: 3, stated: 3, withheld: 0, hypothesis: 2 });
  assert.deepEqual(linkCounts([]), { measured: 0, stated: 0, withheld: 0, hypothesis: 0 });
});

test("only an event whose quote is verified on this read is an event; the rest are cited, not verified", () => {
  const events = [{ kind: "Supply disruption", ...passage("a", "verified") },
    { kind: "Supply disruption", ...passage("b", "changed") }, { kind: "Supply disruption", ...passage("c", "missing") }];
  const split = splitEvents(events);
  assert.deepEqual(split.shown.map((event) => event.evidence.id), ["a"]);
  assert.deepEqual(split.unverified.map((event) => event.evidence.id), ["b", "c"]);
  // The fixture's three copper events are cited but not verified (the synthetic copper thesis cannot be read and no FCX
  // document is served): none is shown as an event.
  const copper = splitEvents(view.research.metals.copper.events);
  assert.equal(copper.shown.length, 0);
  assert.equal(copper.unverified.length, 3);
  assert.ok(verified(passage("v", "verified")) && !verified(passage("u", "unavailable")));
});

test("an HHI link finds the series its ref names, so the coverage can stand beside the range", () => {
  const cobalt = view.research.metals.cobalt.chains[0].links.find((link) =>
    link.kind === "measured" && "stage" in link.ref && link.ref.figure === "hhi") as MeasuredLink;
  assert.equal(cobalt.shown, "5,706–5,839");
  const found = linkIndicators(cobalt.ref, chapter("cobalt"), risk("cobalt"));
  assert.deepEqual([found?.named_share, found?.over_total, found?.hhi_low, found?.hhi_high], ["88.5", false, "5706", "5839"]);
  // Mining and refining take the first stage entry of that kind; reserves take ruling R1's series.
  assert.equal(linkIndicators({ stage: "refining", figure: "hhi" }, chapter("copper"), risk("copper"))?.hhi_low, "2030");
  assert.equal(linkIndicators({ stage: "reserves", figure: "hhi" }, chapter("copper"), risk("copper"))?.hhi_low, "526");
  // A stage the metal does not print, another figure, or another ref names no series.
  assert.equal(linkIndicators({ stage: "refining", figure: "hhi" }, chapter("cobalt"), risk("cobalt")), null);
  assert.equal(linkIndicators({ stage: "mining", figure: "leader" }, chapter("cobalt"), risk("cobalt")), null);
  assert.equal(linkIndicators({ reliance: "2025" }, chapter("cobalt"), risk("cobalt")), null);
  assert.equal(linkIndicators({ iea: "Cobalt", technology: "Electric vehicles" }, chapter("cobalt"), risk("cobalt")), null);
  assert.equal(linkIndicators({ stage: "reserves", figure: "hhi" }, chapter("lithium"), risk("lithium")), null);
});
