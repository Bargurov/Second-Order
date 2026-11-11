// Replies bound to the inputs they were sent for (copperRequests.ts), with replies held back and released out of order,
// and saving bound to the scenario a preview showed (copperActions.saveScenario) against a captured server reply.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { saveScenario, type Preview } from "../src/copperActions.ts";
import { inputKey, Latest, latest } from "../src/copperRequests.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));

/** A reply the test releases when it chooses. */
function held<T>() {
  let release!: (value: T) => void;
  const promise = new Promise<T>((done) => { release = done; });
  return { promise, release };
}

test("equal inputs give equal keys, whatever the key order", () => {
  assert.equal(inputKey({ year: "2035", scenario: "steps", assumptions: { ev: null, mine: null } }),
               inputKey({ assumptions: { mine: null, ev: null }, scenario: "steps", year: "2035" }));
  assert.notEqual(inputKey({ scenario: "steps", year: "2035" }), inputKey({ scenario: "steps", year: "2040" }));
});

test("a reply that arrives after the inputs changed is not used (STEPS 2035 sent, 2040 chosen meanwhile)", async () => {
  const gate = new Latest();
  let current = inputKey({ scenario: "steps", year: "2035" });
  const reply = held<string>();
  const sent = latest(gate, current, () => current, () => reply.promise);
  current = inputKey({ scenario: "steps", year: "2040" });  // The year is changed while the reply is held.
  gate.invalidate();
  reply.release("R = 12,789 for 2035");
  assert.deepEqual(await sent, { used: false });
  const again = latest(gate, current, () => current, async () => "R = 17,801 for 2040");
  assert.deepEqual(await again, { used: true, value: "R = 17,801 for 2040" });
});

test("a reply is not used when the inputs differ, even if nothing invalidated it", async () => {
  const gate = new Latest();
  let current = inputKey({ rate: "8", years: "20" });
  const reply = held<string>();
  const sent = latest(gate, current, () => current, () => reply.promise);
  current = inputKey({ rate: "0", years: "20" });  // Rate 8% sent, rate 0 typed while the reply is held.
  reply.release("CRF 0.101852");
  assert.deepEqual(await sent, { used: false });
});

test("of two requests for the same inputs, only the latest reply is used, whichever arrives first", async () => {
  const gate = new Latest();
  const current = inputKey({ rate: "8", years: "20" });
  const first = held<string>();
  const second = held<string>();
  const a = latest(gate, current, () => current, () => first.promise);
  const b = latest(gate, current, () => current, () => second.promise);
  second.release("second");
  first.release("first");
  assert.deepEqual(await b, { used: true, value: "second" });
  assert.deepEqual(await a, { used: false });
});

test("saving sends exactly the previewed scenario and refuses a record of another scenario", async () => {
  const view = fixture("copper-tools-view.json");
  const preview: Preview = fixture("copper-preview.json");
  const saved = fixture("copper-saved.json");
  const sent: unknown[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (_path: string, init: { body: string }) => {
    sent.push(JSON.parse(init.body));
    return new Response(JSON.stringify(saved), { status: 201, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  try {
    const label = saved.record.label;
    const ok = await saveScenario(view, preview.result, label);
    assert.equal(ok.state, "ready");
    assert.deepEqual(sent[0], { scenario: "steps", year: "2035", assumptions: preview.result.assumptions, label });
    // The page showed another year: a record of STEPS 2035 is not confirmed as that scenario.
    const other = await saveScenario(view, { ...preview.result, year: "2040" }, label);
    assert.equal(other.state, "unconfirmed");
    assert.match(other.state === "unconfirmed" ? other.message : "", /not the scenario that was shown/);
    assert.deepEqual(sent[1], { scenario: "steps", year: "2040", assumptions: preview.result.assumptions, label });
    // Other inputs shown: also refused.
    const inputs = await saveScenario(view, { ...preview.result, assumptions: { ...preview.result.assumptions, ev: null } },
                                      label);
    assert.equal(inputs.state, "unconfirmed");
    const labelled = await saveScenario(view, preview.result, "another label");
    assert.equal(labelled.state, "unconfirmed");
  } finally {
    globalThis.fetch = original;
  }
});
