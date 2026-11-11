// The fuels page's two edge cases, on replies captured from the server on SYNTHETIC data (tests/test_fuels_api.py):
// (a) a change too small to show keeps its direction and says it is under the last shown place, apart from a true
// zero (fuelsText.ts, fuelsSituation.ts); (b) a series far behind the others keeps its price and date, says how far
// behind it is, and the reader refuses anything computed from it (fuels.ts).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { WindowView } from "../src/fuels.ts";
import { fuelsRefusal } from "../src/fuels.ts";
import { canSay, SITUATION_COPY, smallShown, splitDescription, summaryLine } from "../src/fuelsSituation.ts";
import { behindText, changeMoney, changeNumber, changePercent } from "../src/fuelsText.ts";

const MINUS = "−";
const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));
const series = (body: any, role: string) => body.series.find((s: any) => s.role === role);
const windowOf = (name: string, id: string): WindowView =>
  fixture(name).situation.windows.find((w: any) => w.id === id);
const refusal = (name: string, change: (body: any) => void) => {
  const body = fixture(name);
  change(body);
  return fuelsRefusal(body);
};

test("a change under the last shown place shows its direction and less than that place; a true zero shows 0.00", () => {
  assert.equal(changeNumber({ value: "-0.004", shown: "0.00" }), `${MINUS}<0.01`);
  assert.equal(changeNumber({ value: "0.004", shown: "0.00" }), "+<0.01");
  assert.equal(changeNumber({ value: "0", shown: "0.00" }), "0.00");
  assert.equal(changeNumber({ value: "-0.96", shown: "-0.96" }), `${MINUS}0.96`);
  assert.equal(changeNumber({ value: "0.96", shown: "0.96" }), "+0.96");
  assert.equal(changeNumber({ value: "-0.0004", shown: "0.000" }), `${MINUS}<0.001`);
  assert.equal(changeMoney({ value: "-0.004", shown: "0.00" }), `${MINUS}<$0.01`);
  assert.equal(changeMoney({ value: "0.004", shown: "0.00" }), "+<$0.01");
  assert.equal(changeMoney({ value: "0", shown: "0.00" }), "$0.00");
  assert.equal(changeMoney({ value: "6.54", shown: "6.54" }), "+$6.54");
  assert.equal(changeMoney({ value: "-0.04", shown: "-0.04" }), `${MINUS}$0.04`);
});

test("rounding boundaries: half a cent each way still shows as under a cent, a little more shows one cent", () => {
  assert.equal(changeNumber({ value: "0.005", shown: "0.00" }), "+<0.01");
  assert.equal(changeNumber({ value: "-0.005", shown: "0.00" }), `${MINUS}<0.01`);
  assert.equal(changeNumber({ value: "0.0051", shown: "0.01" }), "+0.01");
  assert.equal(changeNumber({ value: "-0.0051", shown: "-0.01" }), `${MINUS}0.01`);
  assert.equal(changeNumber({ value: "0.015", shown: "0.02" }), "+0.02");
});

test("a percent change under its last place takes the change's direction; a true zero stays 0.0", () => {
  assert.equal(changePercent({ shown: "0.0" }, { value: "0.046", shown: "0.05" }), "+<0.1");
  assert.equal(changePercent({ shown: "0.0" }, { value: "-0.046", shown: "-0.05" }), `${MINUS}<0.1`);
  assert.equal(changePercent({ shown: "0.0" }, { value: "0", shown: "0.00" }), "0.0");
  assert.equal(changePercent({ shown: "1.2" }, { value: "0.96", shown: "0.96" }), "+1.2");
  assert.equal(changePercent({ shown: "-0.1" }, { value: "-0.08", shown: "-0.08" }), `${MINUS}0.1`);
});

test("the captured offsetting split with a crack under a cent says which way the crack moved", () => {
  for (const id of ["previous", "week"]) {
    const w = windowOf("fuels-view-subcent.json", id);
    assert.equal(w.split?.label, "offsetting");
    assert.deepEqual(w.split?.crack, { value: "-0.004", shown: "0.00" });
    assert.ok(canSay(w)[0].includes(`+$0.06/bbl with Brent and ${MINUS}<$0.01/bbl with the crack`), canSay(w)[0]);
    assert.ok(splitDescription(w).includes(`${MINUS}<$0.01 with the crack`), splitDescription(w));
  }
  assert.equal(summaryLine(windowOf("fuels-view-subcent.json", "week")),
    "Over about a week to 3 Nov 2026, Brent and the crack moved in opposite directions; the crack fell by less than "
    + "$0.01.");
  assert.equal(smallShown(fixture("fuels-view-subcent.json").situation.windows), true);
  assert.match(SITUATION_COPY.small, /0\.00 is no change/);
});

test("a true zero part is not called small, and a reply without a small change needs no key", () => {
  const w = windowOf("fuels-view-subcent.json", "week");
  const zero = { ...w, split: { ...w.split!, crack: { value: "0", shown: "0.00" }, label: "mostly_crude" as const } };
  assert.equal(summaryLine(zero), "Over about a week to 3 Nov 2026, the basket's change was mostly in Brent.");
  assert.equal(smallShown([windowOf("fuels-view.json", "week"), windowOf("fuels-view.json", "month")]), false);
  // The positive reply's previous window holds gasoline -0.001 on 2.501: -0.04%, shown 0.0, so the key applies.
  const previous = windowOf("fuels-view.json", "previous");
  assert.equal(previous.rows?.gasoline.pct?.shown, "0.0");
  assert.equal(smallShown([previous]), true);
  const rise = { ...w, split: { ...w.split!, crack: { value: "0.004", shown: "0.00" } } };
  assert.ok(summaryLine(rise).endsWith("; the crack rose by less than $0.01."));
});

test("the captured replies with a series behind and with a sub-cent change pass the reader", () => {
  for (const name of ["fuels-view-behind-wti.json", "fuels-view-behind-diesel.json", "fuels-view-subcent.json"]) {
    assert.equal(fuelsRefusal(fixture(name)), null, name);
  }
});

test("WTI a year behind keeps its price and date, and leaves the barrel and Situation Now computed", () => {
  const body = fixture("fuels-view-behind-wti.json");
  assert.equal(series(body, "wti").latest.date, "2025-11-03");
  assert.deepEqual(series(body, "wti").behind, { days: 365, newest: "2026-11-03" });
  assert.equal(body.barrel.state, "computed");
  assert.equal(body.situation.state, "computed");
});

test("diesel a year behind keeps its price and date, and withholds the barrel, the crack history and Situation Now", () => {
  const body = fixture("fuels-view-behind-diesel.json");
  assert.equal(series(body, "diesel").state, "verified");
  assert.equal(series(body, "diesel").latest.date, "2025-11-03");
  assert.equal(body.barrel.state, "withheld");
  assert.deepEqual(body.crack_history, []);
  assert.equal(body.situation.state, "withheld");
});

test("behind must follow the latest dates: dropped, changed or added where it is not due, the reply is refused", () => {
  assert.match(refusal("fuels-view-behind-wti.json", (b) => { series(b, "wti").behind = null; }) ?? "", /behind/);
  assert.match(refusal("fuels-view-behind-wti.json", (b) => { series(b, "wti").behind.days = 364; }) ?? "", /behind/);
  assert.match(refusal("fuels-view-behind-wti.json", (b) => { series(b, "wti").behind.newest = "2026-11-02"; }) ?? "",
    /behind/);
  assert.match(refusal("fuels-view.json", (b) => { series(b, "brent").behind = { days: 11, newest: "2026-11-14" }; })
    ?? "", /behind/);
  assert.match(refusal("fuels-view.json", (b) => { delete series(b, "brent").behind; }) ?? "", /behind/);
  assert.match(refusal("fuels-view-missing.json", (b) => { series(b, "wti").behind = { days: 365, newest: "2026-11-03" }; })
    ?? "", /behind/);
});

test("a barrel computed beside an input that is behind is refused, naming the rule and no value", () => {
  const message = refusal("fuels-view-behind-diesel.json", (b) => { b.barrel = fixture("fuels-view.json").barrel; }) ?? "";
  assert.match(message, /^barrel: .*behind/);
  assert.doesNotMatch(message, /\d\.\d/);
});

test("the line under a series that is behind gives its distance, the newest date and what is withheld", () => {
  const lag = { days: 365, newest: "2026-11-03" };
  assert.equal(behindText(lag, false), "365 days behind the newest price on this page (3 Nov 2026): EIA's file held "
    + "nothing newer for this series at the refresh. It is still a verified price.");
  assert.equal(behindText(lag, true), "365 days behind the newest price on this page (3 Nov 2026): EIA's file held "
    + "nothing newer for this series at the refresh. It is still a verified price; the barrel, the crack and "
    + "Situation now are not computed from it.");
});
