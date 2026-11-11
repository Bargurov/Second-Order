// The metals picks (metalsPicks.ts): which chapters the address asks for, and the address for a set of picks.
import assert from "node:assert/strict";
import { test } from "node:test";
import { METAL_IDS } from "../src/metals.ts";
import { hashFor, matching, picksFrom, searchFor, viewFrom } from "../src/metalsPicks.ts";

const ids = [...METAL_IDS];
const fallback = ["copper", "lithium", "cobalt", "rare-earths", "nickel", "aluminum"];

test("unknown, unsafe and repeated ids are ignored and counted", () => {
  assert.deepEqual(picksFrom("?m=cobalt,nosuch,../x,cobalt", ids, fallback), { picks: ["cobalt"], ignored: 3 });
  assert.deepEqual(picksFrom("?m=cobalt,nosuch,../x", ids, fallback), { picks: ["cobalt"], ignored: 2 });
});

test("the address order is kept, first occurrence first", () => {
  assert.deepEqual(picksFrom("?m=zinc,copper,zinc,gold", ids, fallback), { picks: ["zinc", "copper", "gold"], ignored: 1 });
  assert.deepEqual(picksFrom("?x=1&m=lithium", ids, fallback), { picks: ["lithium"], ignored: 0 });
});

test("an empty or missing m gives the fallback with nothing ignored", () => {
  for (const search of ["", "?", "?m=", "?x=copper", "?m=,"]) {
    assert.deepEqual(picksFrom(search, ids, fallback), { picks: fallback, ignored: 0 }, search);
  }
});

test("nothing valid left gives the fallback, still counting what was ignored", () => {
  assert.deepEqual(picksFrom("?m=nosuch,COPPER", ids, fallback), { picks: fallback, ignored: 2 });
  assert.doesNotThrow(() => picksFrom("?m=%E0%A4", ids, fallback));
});

test("the address for a set of picks", () => {
  assert.equal(searchFor(["cobalt", "lithium"]), "?m=cobalt,lithium");
  assert.equal(searchFor(["copper"]), "?m=copper");
  const round = picksFrom(searchFor(["gold", "rare-earths-heavy"]), ids, fallback);
  assert.deepEqual(round, { picks: ["gold", "rare-earths-heavy"], ignored: 0 });
});

test("the tab and the opened metal come from the address's hash; anything unknown is the overview", () => {
  const picks = ["copper", "cobalt"];
  assert.deepEqual(viewFrom("", picks), { tab: "overview", metal: null });
  assert.deepEqual(viewFrom("#overview", picks), { tab: "overview", metal: null });
  assert.deepEqual(viewFrom("#method", picks), { tab: "method", metal: null });
  assert.deepEqual(viewFrom("#by-metal", picks), { tab: "by-metal", metal: null });
  assert.deepEqual(viewFrom("#by-metal:cobalt", picks), { tab: "by-metal", metal: "cobalt" });
  // A metal that is not picked is dropped, never added to the picks; anything else falls back to the overview.
  assert.deepEqual(viewFrom("#by-metal:gold", picks), { tab: "by-metal", metal: null });
  for (const hash of ["#nosuch", "#method:copper", "#%E0%A4", "#", "#BY-METAL"]) {
    assert.deepEqual(viewFrom(hash, picks), { tab: "overview", metal: null }, hash);
  }
  for (const hash of ["#by-metal:", "#by-metal:../x", "#by-metal:COBALT"]) {
    assert.deepEqual(viewFrom(hash, picks), { tab: "by-metal", metal: null }, hash);
  }
});

test("the hash for a tab and metal reads back the same", () => {
  assert.equal(hashFor("overview", null), "");
  assert.equal(hashFor("overview", "copper"), "");
  assert.equal(hashFor("method", "copper"), "#method");
  assert.equal(hashFor("by-metal", null), "#by-metal");
  assert.equal(hashFor("by-metal", "rare-earths"), "#by-metal:rare-earths");
  assert.deepEqual(viewFrom(hashFor("by-metal", "rare-earths"), ["rare-earths"]), { tab: "by-metal", metal: "rare-earths" });
});

test("finding a metal by name: case, spaces and brackets do not matter, the order is kept", () => {
  const frames = [{ id: "rare-earths", name: "Rare earths" }, { id: "rare-earths-heavy", name: "Rare earths (heavy)" },
    { id: "niobium-columbium", name: "Niobium (columbium)" }, { id: "lead", name: "Lead" }];
  assert.deepEqual(matching(frames, "").map((f) => f.id), frames.map((f) => f.id));
  assert.deepEqual(matching(frames, "  RARE ").map((f) => f.id), ["rare-earths", "rare-earths-heavy"]);
  assert.deepEqual(matching(frames, "(heavy").map((f) => f.id), ["rare-earths-heavy"]);
  assert.deepEqual(matching(frames, "columbium").map((f) => f.id), ["niobium-columbium"]);
  assert.deepEqual(matching(frames, "rare earths heavy").map((f) => f.id), ["rare-earths-heavy"]);
  assert.deepEqual(matching(frames, "zzz"), []);
});
