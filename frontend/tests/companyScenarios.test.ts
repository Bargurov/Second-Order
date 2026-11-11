// The Scenarios tab's reader (companyScenarios.ts) against replies captured from the server
// (tests/fixtures/company-fcx-scenario-*.json, written by tests/test_company_scenarios.py) and the page's view
// (company-fcx-view.json, company-fcx-unavailable.json).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { companyRefusal } from "../src/companyResearch.ts";
import {
  beyondOneStep, modeState, money, priceProblem, priceText, scenarioRefusal, USES, volumeProblem, volumeText,
} from "../src/companyScenarios.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));
const view = () => fixture("company-fcx-view.json");
const PV = { price: "6.60", volume: "900" };
const CF = { price: "6.37" };
const pv = (change: (reply: any) => void = () => {}, page = view()) => {
  const reply = fixture("company-fcx-scenario-price-volume.json");
  change(reply);
  return scenarioRefusal(reply, page, "price_volume", PV);
};
const cf = (change: (reply: any) => void = () => {}, page = view()) => {
  const reply = fixture("company-fcx-scenario-cash-flow.json");
  change(reply);
  return scenarioRefusal(reply, page, "cash_flow", CF);
};

test("the captured replies pass, each for the inputs it was computed for", () => {
  assert.equal(pv(), null);
  assert.equal(cf(), null);
  const reply = fixture("company-fcx-scenario-price-volume.json");
  assert.deepEqual(reply.result, { value: "5940", base: "5687.5", change: "252.5", price_effect: "90",
    volume_effect: "162.5" });
  assert.deepEqual(fixture("company-fcx-scenario-cash-flow.json").result, { price_change: "-0.13", steps: "-1.3",
    change: "-97.5" });
});

test("a reply for other inputs is refused, so an earlier result never stands for the current inputs", () => {
  const reply = fixture("company-fcx-scenario-price-volume.json");
  assert.match(scenarioRefusal(reply, view(), "price_volume", { price: "6.60", volume: "875" }) ?? "",
    /answers other inputs/);
  assert.match(scenarioRefusal(reply, view(), "price_volume", { price: "6.6", volume: "900" }) ?? "",
    /answers other inputs/);
  assert.match(scenarioRefusal(reply, view(), "cash_flow", { price: "6.60" }) ?? "", /another calculation/);
});

test("every result is recomputed exactly; a wrong one is refused naming its place, not its value", () => {
  for (const [key, wrong] of [["value", "5941"], ["base", "5687.6"], ["change", "252.4"], ["price_effect", "90.001"],
    ["volume_effect", "162"]] as const) {
    const message = pv((reply) => { reply.result[key] = wrong; }) ?? "";
    assert.match(message, new RegExp(`result\\.${key}`), key);
    assert.ok(!message.includes(wrong), message);
  }
  assert.match(cf((reply) => { reply.result.change = "-97"; }) ?? "", /result\.change/);
  assert.match(cf((reply) => { reply.result.steps = "-1.2"; }) ?? "", /result\.steps/);
  assert.match(cf((reply) => { reply.result.price_change = "-0.12"; }) ?? "", /result\.price_change/);
});

test("a split that does not add up is refused even when each part is consistent with the others", () => {
  const message = pv((reply) => { reply.result.price_effect = "100"; reply.result.change = "262.5"; }) ?? "";
  assert.match(message, /result\.(price_effect|change)/);
});

test("a reply must use the page's own verified records, with their values", () => {
  assert.match(pv((reply) => { reply.uses.price.value = "6.4"; }) ?? "", /uses\.price/);
  assert.match(cf((reply) => { reply.uses.sensitivity.record = "k25-sensitivity-ocf-copper-fy2026"; }) ?? "",
    /uses\.sensitivity/);
  assert.match(cf((reply) => { reply.uses.volume = { record: "r3-out-cu-sales-q4-2026", value: "875" }; }) ?? "",
    /uses/);
  const page = view();
  Object.assign(page.records["r3-out-cu-price-q4-2026"], { state: "withheld", value: null, display: null, quote: null,
    problem: "test" });
  assert.match(pv(() => {}, page) ?? "", /not shown on the page/);
});

test("a reply that stores, calls a provider or names another version is refused", () => {
  assert.match(pv((reply) => { reply.stored = true; }) ?? "", /stored/);
  assert.match(pv((reply) => { reply.provider_called = true; }) ?? "", /provider_called/);
  assert.match(pv((reply) => { reply.view_version = "company-scenario-0.0"; }) ?? "", /view_version/);
  assert.match(pv((reply) => { reply.unit = "USD billions"; }) ?? "", /unit/);
  assert.match(pv((reply) => { reply.rests_on = ["10k-2025"]; }) ?? "", /rests_on/);
  assert.match(pv((reply) => { reply.result.extra = "1"; }) ?? "", /result/);
});

test("each calculation is available only while every record it uses is shown", () => {
  for (const mode of ["price_volume", "cash_flow"] as const) {
    assert.deepEqual(modeState(view(), mode), { available: true, problem: null }, mode);
    const blocked = modeState(fixture("company-fcx-unavailable.json"), mode);
    assert.equal(blocked.available, false, mode);
    assert.match(blocked.problem ?? "", /results release/);
  }
  assert.deepEqual(USES.cash_flow, { price: "r3-out-cu-price-q4-2026", sensitivity: "r3-sens-ocf-copper",
    step: "r3-sens-ocf-copper-step" });
});

test("the input rules are the server's: dollars per pound to the cent, million pounds with one decimal", () => {
  for (const ok of ["6.50", "6.5", "0.01", "100", "100.00", "12"]) assert.equal(priceProblem(ok), null, ok);
  for (const bad of ["", "0", "-1", "6.505", "1e2", "6,50", "abc", ".5", "6."]) {
    assert.ok(priceProblem(bad), bad);
  }
  assert.match(priceProblem("14330") ?? "", /per pound/);
  assert.match(priceProblem("14330") ?? "", /tonne/);
  for (const ok of ["875", "875.5", "0.1", "5000"]) assert.equal(volumeProblem(ok), null, ok);
  for (const bad of ["", "0", "-5", "875.25", "5000.1", "875000", "1,000"]) {
    assert.match(volumeProblem(bad) ?? "", /million pounds/, bad);
  }
});

test("amounts read with their unit and sign, exactly", () => {
  assert.equal(money("5775"), "$5,775 million");
  assert.equal(money("5687.5"), "$5,687.5 million");
  assert.equal(money("87.5", true), "+$87.5 million");
  assert.equal(money("-97.5", true), "−$97.5 million");
  assert.equal(money("0", true), "$0 million");
  assert.equal(money("0.001"), "$0.001 million");
  assert.equal(priceText("6.6"), "$6.60");
  assert.equal(priceText("100"), "$100.00");
  assert.equal(volumeText("1234.5"), "1,234.5 million pounds");
});

test("a price change of more than one of the company's steps is told apart, in either direction", () => {
  for (const steps of ["5", "-1.3", "1.1", "-750"]) assert.equal(beyondOneStep(steps), true, steps);
  for (const steps of ["1", "-1", "0.5", "-0.1", "0"]) assert.equal(beyondOneStep(steps), false, steps);
});

test("the page's scenarios must name exactly the records each calculation uses", () => {
  const body = view();
  assert.equal(companyRefusal(body), null);
  body.page.scenarios.cash_flow.base[1].record = "k25-sensitivity-ocf-copper-fy2026";
  body.records["k25-sensitivity-ocf-copper-fy2026"] ??= { ...body.records["r3-sens-ocf-copper"],
    id: "k25-sensitivity-ocf-copper-fy2026" };
  assert.match(companyRefusal(body) ?? "", /page\.scenarios/);
});
