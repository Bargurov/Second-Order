// The fuels reader (fuels.ts) against replies captured from the server on SYNTHETIC data (tests/fuels_fakes.py).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { make } from "../src/copperNumbers.ts";
import { fetchFuels, FUELS_VIEW_VERSION, fuelsRefusal } from "../src/fuels.ts";
import { monthBefore, splitLabel } from "../src/fuelsSituationReader.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));
const refusal = (change: (body: any) => void, name = "fuels-view.json") => {
  const body = fixture(name);
  change(body);
  return fuelsRefusal(body);
};
const series = (body: any, role: string) => body.series.find((s: any) => s.role === role);

test("the captured replies pass", () => {
  for (const name of ["fuels-view.json", "fuels-view-earlier.json", "fuels-view-missing.json", "fuels-view-stale.json",
    "fuels-view-analysis.json"]) {
    assert.equal(fuelsRefusal(fixture(name)), null);
  }
  assert.equal(FUELS_VIEW_VERSION, "fuels-view-0.5");
});

test("a synthetic mark is absent or exactly true: anything else is refused", () => {
  assert.equal(refusal((b) => { b.synthetic = true; }), null);
  assert.equal(refusal((b) => { b.synthetic = true; }, "fuels-view-missing.json"), null);
  for (const bad of [false, "true", 1, null]) {
    assert.match(refusal((b) => { b.synthetic = bad; }) ?? "", /synthetic/, String(bad));
  }
});

test("a crack that does not follow its inputs is refused, naming its place", () => {
  const message = refusal((b) => { b.barrel.crack.value = "31"; });
  assert.match(message ?? "", /barrel\.crack/);
  assert.doesNotMatch(message ?? "", /31/);
  assert.notEqual(refusal((b) => { b.barrel.basket.value = "113"; }), null);
  assert.notEqual(refusal((b) => { b.barrel.change.crack.value = "-1"; }), null);
});

test("a shown value that is not the half-even rounding is refused", () => {
  assert.match(refusal((b) => { b.barrel.basket.shown = "112.01"; }) ?? "", /barrel\.basket/);
  assert.notEqual(refusal((b) => { b.barrel.inputs.gasoline.shown = "2.50"; }), null);
  assert.notEqual(refusal((b) => { series(b, "brent").latest.shown = "80.0"; }), null);
});

test("an input that is not the series value on the barrel date is refused", () => {
  assert.notEqual(refusal((b) => { b.barrel.inputs.brent = { value: "81", shown: "81.00" }; }), null);
  assert.notEqual(refusal((b) => { b.barrel.previous.diesel = { value: "3.002", shown: "3.002" }; }), null);
  assert.notEqual(refusal((b) => { b.barrel.previous_date = b.barrel.date; }), null);
});

test("the sign must match the crack", () => {
  assert.notEqual(refusal((b) => { b.barrel.crack.sign = "negative"; }), null);
  assert.notEqual(refusal((b) => { b.barrel.crack.sign = "positive"; }, "fuels-view-earlier.json"), null);
});

test("a withheld barrel with a number is refused", () => {
  assert.notEqual(refusal((b) => { b.barrel.basket = { value: "112", shown: "112.00" }; }, "fuels-view-missing.json"), null);
  assert.notEqual(refusal((b) => { b.barrel.date = "2026-11-03"; }, "fuels-view-missing.json"), null);
});

test("a value on an unverified series is refused", () => {
  assert.notEqual(refusal((b) => {
    series(b, "wti").latest = { date: "2026-11-03", value: "70", shown: "70.00", published_on: null };
  }, "fuels-view-missing.json"), null);
  assert.notEqual(refusal((b) => { series(b, "wti").state = "refused"; }), null);
  assert.notEqual(refusal((b) => { series(b, "wti").kind = "missing"; }), null);
  assert.notEqual(refusal((b) => { series(b, "brent").state = "mystery"; }), null);
});

test("an unverified snapshot allows no verified series and no computed barrel", () => {
  assert.notEqual(refusal((b) => { b.snapshot.state = "changed"; }), null);
});

test("a computed barrel needs its three inputs verified", () => {
  assert.notEqual(refusal((b) => {
    const s = series(b, "diesel");
    Object.assign(s, { state: "missing", kind: "missing", latest: null, history: [], problem: "None." });
  }), null);
});

test("a crack history row that does not follow the histories is refused", () => {
  assert.match(refusal((b) => { b.crack_history[3][1] = "1"; }) ?? "", /crack_history/);
  assert.notEqual(refusal((b) => { b.crack_history.pop(); }), null);
  assert.notEqual(refusal((b) => { b.crack_history.reverse(); }), null);
});

test("a current note bound to another snapshot is refused", () => {
  assert.match(refusal((b) => { b.note.snapshot_id = "0".repeat(64); }) ?? "", /note/);
});

test("an earlier note must carry the latest barrel's shown values", () => {
  assert.notEqual(refusal((b) => { b.note.now.brent = "114.00"; }, "fuels-view-earlier.json"), null);
  assert.notEqual(refusal((b) => { b.note.now = null; }, "fuels-view-earlier.json"), null);
  assert.notEqual(refusal((b) => { b.note.state = "earlier"; b.note.then = null; }), null);
});

test("an earlier note whose latest barrel is withheld may have no now, and says why", () => {
  const withheld = (b: any) => {
    for (const s of b.series) { Object.assign(s, { state: "missing", kind: "missing", latest: null, history: [], problem: "None." }); }
    b.snapshot.state = "missing"; b.snapshot.id = null;
    Object.assign(b.barrel, { state: "withheld", problem: "No data.", date: null, previous_date: null, inputs: null,
      previous: null, basket: null, crack: null, change: null, published_on: null, retrieved_at: null });
    b.crack_history = [];
    Object.assign(b.situation, { state: "withheld", problem: "No data.", date: null, age_days: null, stale: false,
      newer: [], windows: [] });
    b.note.now = null; b.note.problem = "The latest prices are withheld: No data.";
  };
  assert.equal(refusal(withheld, "fuels-view-earlier.json"), null);
  assert.notEqual(refusal((b) => { withheld(b); b.note.problem = null; }, "fuels-view-earlier.json"), null);
});

const windowOf = (body: any, id: string) => body.situation.windows.find((w: any) => w.id === id);
const named = (change: (body: any) => void, place: RegExp, name = "fuels-view.json") => {
  const message = refusal(change, name);
  assert.match(message ?? "", place);
  assert.doesNotMatch(message ?? "", /\d\.\d/);
};

test("Situation Now: a changed split part, a wrong label or a pct off in the last place is refused", () => {
  named((b) => { windowOf(b, "week").split.diesel_part.value = "2.283"; }, /situation\.windows\[1\]\.split\.diesel_part/);
  named((b) => { windowOf(b, "week").split.label = "mostly_crude"; }, /split\.label/);
  named((b) => { windowOf(b, "week").rows.brent.pct.shown = "2.3"; }, /rows\.brent\.pct/);
  named((b) => { windowOf(b, "previous").rows.crack.change.shown = "0.00"; }, /rows\.crack\.change/);
  named((b) => { windowOf(b, "previous").rows.basket.pct = null; }, /basket\.pct/);
});

test("Situation Now: a week start outside tolerance or a wrong target is refused", () => {
  named((b) => { windowOf(b, "week").from = "2026-10-20"; }, /situation\.windows\[1\]\.from/);
  named((b) => { windowOf(b, "week").target = "2026-10-28"; }, /windows\[1\]\.target/);
  named((b) => { windowOf(b, "month").from = "2026-10-01"; }, /windows\[2\]\.from/);
  named((b) => {
    Object.assign(windowOf(b, "week"), { state: "unavailable", reason: "None.", from: null, rows: null, split: null });
  }, /windows\[1\]\.state/);
  named((b) => { windowOf(b, "previous").from = "2026-10-30"; }, /windows\[0\]\.from/);
});

test("Situation Now: age, stale and newer must follow the snapshot and the series", () => {
  named((b) => { b.situation.stale = true; }, /situation\.stale/);
  named((b) => { b.situation.stale = false; }, /situation\.stale/, "fuels-view-stale.json");
  named((b) => { b.situation.age_days = 4; }, /situation\.age_days/);
  named((b) => { b.situation.date = "2026-11-02"; }, /situation\.date/);
  named((b) => { b.situation.newer = [{ role: "wti", date: "2026-11-04" }]; }, /situation\.newer/);
  named((b) => { series(b, "wti").latest = { date: "2026-11-05", value: "70", shown: "70.00", published_on: null };
                 series(b, "wti").history = [["2026-11-05", "70"]]; }, /situation\.newer/);
});

test("Situation Now: a computed situation beside a withheld barrel, or the reverse, is refused", () => {
  assert.equal(refusal((b) => { b.situation = fixture("fuels-view-missing.json").situation; b.situation.state = "computed"; },
    "fuels-view-missing.json"), "situation: is computed beside a withheld barrel");
  assert.equal(refusal((b) => { b.situation = fixture("fuels-view-missing.json").situation; }),
    "situation: is withheld beside a computed barrel");
  named((b) => { b.situation.windows = [{}]; }, /situation\.windows/, "fuels-view-missing.json");
});

test("the month target is the same day of the previous month, clamped to that month's length", () => {
  assert.equal(monthBefore("2026-01-15"), "2025-12-15");  // January goes back to December of the year before
  assert.equal(monthBefore("2026-01-31"), "2025-12-31");
  assert.equal(monthBefore("2026-03-31"), "2026-02-28");
  assert.equal(monthBefore("2024-03-31"), "2024-02-29");  // a leap year
  assert.equal(monthBefore("2024-03-29"), "2024-02-29");
  assert.equal(monthBefore("2026-05-31"), "2026-04-30");
  assert.equal(monthBefore("2026-11-03"), "2026-10-03");
});

test("the split label's thresholds are inclusive at exactly two thirds and one third", () => {
  const r = (n: bigint, d = 1n) => make(n, d);
  assert.equal(splitLabel(r(2n), r(1n)), "mostly_crude");  // Brent's share exactly 2/3
  assert.equal(splitLabel(r(1n), r(2n)), "mostly_crack");  // exactly 1/3
  assert.equal(splitLabel(r(-2n), r(-1n)), "mostly_crude");
  assert.equal(splitLabel(r(-1n), r(-2n)), "mostly_crack");
  assert.equal(splitLabel(r(1999n, 1000n), r(1n)), "both");  // just under 2/3
  assert.equal(splitLabel(r(1001n, 1000n), r(2n)), "both");  // just over 1/3
  assert.equal(splitLabel(r(0n), r(0n)), "unchanged");
  assert.equal(splitLabel(r(2n), r(-1n)), "offsetting");
  assert.equal(splitLabel(r(0n), r(-3n)), "mostly_crack");
  assert.equal(splitLabel(r(3n), r(0n)), "mostly_crude");
});

test("drivers and transmission: order, lists, https and fields are checked; not_written passes", () => {
  named((b) => { b.drivers.items.reverse(); }, /drivers\.items\[0\]\.id/);
  named((b) => { b.transmission.items[2].id = "aviation"; }, /transmission\.items\[2\]\.id/);
  named((b) => { b.drivers.items[0].acts_on = "other"; }, /drivers\.items\[0\]\.acts_on/);
  named((b) => { b.transmission.items[0].effect = "up"; }, /transmission\.items\[0\]\.effect/);
  named((b) => { b.drivers.items[1].sources[0].url = "http://example.org/x"; }, /drivers\.items\[1\]\.sources\[0\]\.url/);
  named((b) => { b.transmission.items[0].sources[0].url = "http://example.org/x"; }, /transmission\.items\[0\]\.sources\[0\]\.url/);
  named((b) => { b.drivers.items[0].extra = 1; }, /drivers\.items\[0\]/);
  named((b) => { b.transmission.items[0].chain = ["a", "b"]; }, /transmission\.items\[0\]\.chain/);
  named((b) => { b.transmission.items[0].lag_sourced = "yes"; }, /lag_sourced/);
  named((b) => { b.drivers.kind = "transmission"; }, /drivers\.kind/);
  named((b) => { b.drivers = { state: "written" }; }, /drivers/);
  assert.equal(refusal((b) => { b.drivers = { state: "not_written" }; b.transmission = { state: "not_written" }; }), null);
  assert.notEqual(refusal((b) => { b.drivers = { state: "not_written", items: [] }; }), null);
});

test("events must stay not_connected", () => {
  named((b) => { b.events.state = "connected"; }, /events\.state/);
  assert.notEqual(refusal((b) => { delete b.events; }), null);
});

test("a wrong version or a provider call is refused", () => {
  assert.match(refusal((b) => { b.view_version = "fuels-view-0.1"; }) ?? "", /view_version/);
  assert.match(refusal((b) => { b.provider_called = true; }) ?? "", /provider_called/);
  assert.notEqual(fuelsRefusal(null), null);
  assert.notEqual(fuelsRefusal({}), null);
});

test("fetchFuels reads a good reply, maps 503 to not-prepared and refuses a bad one", async () => {
  const original = globalThis.fetch;
  const reply = (status: number, body: unknown) =>
    (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
  try {
    const signal = new AbortController().signal;
    globalThis.fetch = reply(200, fixture("fuels-view.json"));
    assert.equal((await fetchFuels(signal)).state, "ready");
    globalThis.fetch = reply(503, { detail: "Not prepared." });
    assert.deepEqual(await fetchFuels(signal), { state: "not-prepared", message: "Not prepared." });
    const bad = fixture("fuels-view.json");
    bad.barrel.crack.value = "31";
    globalThis.fetch = reply(200, bad);
    assert.equal((await fetchFuels(signal)).state, "error");
    globalThis.fetch = (async () => { throw new TypeError("down"); }) as typeof fetch;
    assert.equal((await fetchFuels(signal)).state, "error");
  } finally {
    globalThis.fetch = original;
  }
});
