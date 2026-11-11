// The exposure map's reading of a served thesis (thesisExposureMap.ts), against the replies the backend serves for the
// SYNTHETIC copper thesis (fixtures/thesis-*.json): every source present, one changed source with one passage no
// longer found (mover-2), and no retained sources at all. The map is built only from the reply's structured fields
// (a company's side, the reason it moves, the ids it cites and its reason's measured figures) and computes no number.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { ThesisView } from "../src/thesis.ts";
import {
  CONCEPTS, LINK_WORDS, STAGES_OF, STAGE_WORDS, exposureMap, laneLabel, moverLabel,
} from "../src/thesisExposureMap.ts";

const fixture = (name: string): ThesisView =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const available = fixture("thesis-available.json");
const revalidation = fixture("thesis-revalidation.json");
const unavailable = fixture("thesis-unavailable.json");
const copy = <T>(value: T): T => structuredClone(value);

test("every company the thesis moves is one lane on its own side, in file order, with its side's stages", () => {
  const map = exposureMap(available);
  assert.deepEqual(map.lanes.map((lane) => [lane.id, lane.company, lane.side]),
    available.exposure.moved.map((moved) => [moved.id, moved.company, moved.side]));
  for (const lane of map.lanes) assert.deepEqual(lane.stages, STAGES_OF[lane.side]);
  assert.deepEqual(STAGES_OF.producer, ["revenue", "margin", "cash_flow"]);
  assert.deepEqual(STAGES_OF.consumer, ["input_cost", "selling_price", "margin", "cash_flow"]);
  assert.deepEqual(map.counts, { producer: 1, consumer: 2, movers: 2 });
});

test("revenue, input cost, margin and cash flow are distinct stages, each in its own words", () => {
  const keys = Object.keys(STAGE_WORDS);
  assert.deepEqual(keys.sort(), ["cash_flow", "input_cost", "margin", "revenue", "selling_price"]);
  for (const field of ["name", "what", "condition"] as const) {
    const values = keys.map((key) => STAGE_WORDS[key as keyof typeof STAGE_WORDS][field]);
    assert.equal(new Set(values).size, values.length, `every stage has its own ${field}`);
  }
  // A producer's price change reaches revenue before any cost; a user's reaches its input cost, then its own prices.
  assert.ok(!STAGES_OF.producer.includes("input_cost"));
  assert.ok(!STAGES_OF.consumer.includes("revenue"));
  // A margin is not revenue, and cash flow is not margin: each stage says what else moves it.
  assert.match(STAGE_WORDS.margin.what, /cost/i);
  assert.match(STAGE_WORDS.cash_flow.what, /working capital|inventory/i);
});

test("a lane shows the filing's figure and its metric exactly as served, and computes nothing", () => {
  const map = exposureMap(available);
  for (const lane of map.lanes) {
    const moved = available.exposure.moved.find((item) => item.id === lane.id)!;
    assert.equal(lane.shown, true);
    assert.deepEqual(lane.statement, moved.how);
    if (moved.amount!.kind === "stated") {
      assert.deepEqual(lane.stated, moved.amount!.figure);
      assert.equal(lane.metric, moved.amount!.figure.measure);  // Verbatim: never renamed to another measure.
      assert.equal(lane.computed, null);
    } else {
      assert.equal(lane.stated, null);
      assert.equal(lane.metric, null);
      assert.deepEqual(lane.computed, { usdPerUnit: moved.usd_per_unit, sharePct: moved.share_pct });
    }
  }
  // Whatever the served metric says is what the lane says, even a wording the map has never seen.
  const renamed = copy(available);
  const first = renamed.exposure.moved[0];
  if (first.amount?.kind === "stated") first.amount.figure.measure = "Synthetic stated change in any line";
  assert.equal(exposureMap(renamed).lanes[0].metric, "Synthetic stated change in any line");
});

test("a lane keeps its statement's served status, so an author's reading is not shown as a source statement", () => {
  const lanes = exposureMap(available).lanes;
  assert.deepEqual(lanes.map((lane) => lane.statement?.status),
    available.exposure.moved.map((moved) => moved.how?.status));
  assert.ok(lanes.some((lane) => lane.statement?.status === "interpretation"));
});

test("a withheld lane carries its frame only: company, side and stages, no statement, figure or metric", () => {
  const map = exposureMap(unavailable);
  assert.equal(map.lanes.length, unavailable.exposure.moved.length);
  for (const lane of map.lanes) {
    assert.equal(lane.shown, false);
    assert.equal(lane.statement, null);
    assert.equal(lane.stated, null);
    assert.equal(lane.metric, null);
    assert.equal(lane.computed, null);
    assert.deepEqual(lane.stages, STAGES_OF[lane.side]);
  }
});

test("accessible names come from the frame only and never carry a withheld figure", () => {
  const labels = unavailable.labels;
  for (const lane of exposureMap(unavailable).lanes) {
    const label = laneLabel(lane, labels);
    assert.equal(label, `${lane.company}, ${labels.sides[lane.side].split(":")[0].toLowerCase()}`);
    assert.doesNotMatch(label, /\d/);
  }
  for (const mover of exposureMap(unavailable).movers) {
    const label = moverLabel(mover);
    assert.ok(label.startsWith(mover.company));
    assert.doesNotMatch(label, /\d/, "a withheld reason title is not named");
  }
});

test("a company whose cited figures include its reason's latest measured figure is that reason's measure", () => {
  const changed = copy(available);
  const mover = changed.exposure.movers[0];
  const reason = changed.reasons.find((item) => item.id === mover.moves)!;
  mover.cites = [...mover.cites!, reason.measure!.latest.id];
  const link = exposureMap(changed).movers[0];
  assert.equal(link.kind, "measure");
  assert.equal(link.link, "stated");
});

test("a company whose figures are not its reason's measure is related to it, never shown as measuring it", () => {
  const links = exposureMap(available).movers;
  assert.deepEqual(links.map((link) => [link.id, link.company, link.reason, link.kind, link.link]),
    available.exposure.movers.map((mover) => [mover.id, mover.company, mover.moves, "related", "unmeasured"]));
  for (const link of links) {
    const reason = available.reasons.find((item) => item.id === link.reason)!;
    assert.equal(link.reasonTitle, reason.title);
    assert.equal(link.reasonStatus, reason.status);
  }
});

test("a company's link is withheld when it or its reason is not available, and says nothing about the measure", () => {
  const links = exposureMap(revalidation).movers;
  const byId = new Map(links.map((link) => [link.id, link]));
  // mover-2 cites a passage no longer found where cited; its reason rests on the changed source.
  assert.equal(byId.get("mover-2")!.kind, "withheld");
  assert.equal(byId.get("mover-2")!.link, null);
  assert.equal(byId.get("mover-2")!.reasonStatus, null);
  // mover-1 and its reason both check: its link is read.
  assert.equal(byId.get("mover-1")!.kind, "related");
  for (const link of exposureMap(unavailable).movers) {
    assert.equal(link.kind, "withheld");
    assert.equal(link.link, null);
    assert.equal(link.reasonStatus, null);
    const reason = unavailable.reasons.find((item) => item.id === link.reason)!;
    assert.equal(link.reasonTitle, reason.title);  // null when the title states a figure (ruling R9).
  }
  // A reason that is available but whose company is withheld is not read either.
  const changed = copy(available);
  changed.exposure.movers[0].state = "needs_revalidation";
  const withheld = exposureMap(changed).movers[0];
  assert.equal(changed.reasons.find((item) => item.id === withheld.reason)!.state, "available");
  assert.deepEqual([withheld.kind, withheld.link, withheld.reasonStatus], ["withheld", null, null]);
});

test("the three kinds of line are told apart in words, and none is said to prove a cause", () => {
  assert.deepEqual(Object.keys(LINK_WORDS).sort(), ["conditional", "stated", "unmeasured"]);
  const names = Object.values(LINK_WORDS).map((words) => words.name);
  assert.equal(new Set(names).size, 3);
  for (const words of Object.values(LINK_WORDS)) assert.doesNotMatch(words.what, /\bproves?\b(?! nothing)/i);
});

test("the plain notes explain incidence, pass-through and operating exposure", () => {
  assert.deepEqual(CONCEPTS.map((concept) => concept.id), ["incidence", "pass-through", "operating-exposure"]);
  const text = (id: string) => CONCEPTS.find((concept) => concept.id === id)!.text;
  assert.match(text("incidence"), /bears/i);
  // Passing a cost on does not by itself keep profit unchanged: timing, spreads and inventory accounting.
  for (const part of [/timing|delay|later/i, /spread/i, /inventor/i]) assert.match(text("pass-through"), part);
  // A share of sales answers a different question from a sensitivity of one line.
  assert.match(text("operating-exposure"), /share of sales/i);
  assert.match(text("operating-exposure"), /sensitivity/i);
});

test("the map's own words state no price direction and make no recommendation", () => {
  const own = [
    ...Object.values(STAGE_WORDS).flatMap((words) => [words.name, words.what, words.condition]),
    ...Object.values(LINK_WORDS).flatMap((words) => [words.name, words.what]),
    ...CONCEPTS.flatMap((concept) => [concept.term, concept.text]),
  ].join(" \n ").toLowerCase();
  for (const pattern of [/\b(?:higher|lower|rising|falling) (?:copper )?prices?\b/, /\bprices? (?:will|would|should|could|may)\b/,
    /\b(?:upside|downside|bullish|bearish)\b/, /\b(?:buy|sell)\b/, /\brecommend/, /\bprices? (?:rises?|falls?)\b/]) {
    assert.doesNotMatch(own, pattern);
  }
});
