// Copper event chains, against replies the backend serves (captured by tests/test_event_chain_api.py into
// fixtures/event-chains-*.json): available, one changed record, one changed document. The reader is fail-closed and
// names the place and rule of each refusal, so each test proves the rule it is about. Saves are one POST each; a lost
// reply is settled from the saved history and never sent again.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { bindAdminAccount } from "../src/admin/adminApi.ts";
import {
  EVENT_CHAIN_HEADER, eventChainsRefusal, fetchEventChains, maskedText, readingBody, reviewBody, saveReading,
  saveReview, settle, type ChainView, type EventChainsView, type ReadingBody, type ReviewBody, type SentSave,
} from "../src/eventChains.ts";

const fixture = (name: string): EventChainsView =>
  JSON.parse(readFileSync(new URL(`./fixtures/event-chains-${name}.json`, import.meta.url), "utf8"));
const copy = <T>(value: T): T => structuredClone(value);
const PLACE = "chains[synthetic-world-chain]";

function refusalOf(name: string, change: (chain: ChainView) => void): string | null {
  const view = fixture(name);
  change(view.chains[0]);
  return eventChainsRefusal(view);
}
function refusedAt(place: string, name: string, change: (chain: ChainView) => void): void {
  const refusal = refusalOf(name, change);
  assert.ok(refusal?.startsWith(`${PLACE}${place}: `), `expected a refusal at ${place}, got ${refusal}`);
  assert.doesNotMatch(refusal, /Synthetic|PTFI/, "a refusal names a place, never a value");
}

test("reads each captured fixture", () => {
  for (const name of ["available", "evidence-changed", "withheld", "two-versions"]) {
    assert.equal(eventChainsRefusal(fixture(name)), null, name);
  }
  assert.equal(maskedText("expects 85% in 2026, see step 3.", 5),
    "expects [figure withheld] in [figure withheld], see step 3.");
  assert.equal(maskedText("see step 9 and 4,120", 5), "see step [figure withheld] and [figure withheld]");
});

test("refuses a withheld step that carries a quote", () => {
  refusedAt(".steps[2]", "withheld", (chain) => {
    const step = chain.steps[2];
    if (step.kind === "stated") step.quote = "A quote that must stay withheld.";
  });
  refusedAt(".steps[1].quote", "evidence-changed", (chain) => {
    const step = chain.steps[1];
    if (step.kind === "stated") step.quote = "Both a quote and a changed state.";
  });
});

test("refuses a masked owner text that still holds a figure outside step references", () => {
  const view = fixture("withheld");
  view.chains[0].history.readings[0].line = "Test line: the company expects 85% in [figure withheld], see step 3.";
  assert.match(eventChainsRefusal(view) ?? "", /^chains\[synthetic-world-chain\]\.history\.readings\[0\]\.line: /);
  const notes = fixture("withheld");
  notes.chains[0].history.reviews[1].notes = "Checked each of 4 steps.";
  assert.match(eventChainsRefusal(notes) ?? "", /history\.reviews\[1\]\.notes: /);
  // A step reference is not a figure; the same text is read while no basis document fails.
  const shown = fixture("available");
  assert.equal(eventChainsRefusal(shown), null);
  // The mask flag follows the documents: not masked while a document fails is refused.
  refusedAt(".history.readings[0].masked", "withheld", (chain) => { chain.history.readings[0].masked = false; });
});

test("refuses an approval shown as current on a chain that is not available", () => {
  refusedAt(".approval", "available", (chain) => {
    chain.state = "evidence_changed";
    chain.reasons = ["A reason."];
  });
  refusedAt(".state", "evidence-changed", (chain) => { chain.state = "available"; chain.reasons = []; });
  refusedAt(".binding.approval_id", "available", (chain) => { chain.binding.approval_id = null; });
});

test("refuses a changed item without both pinned and current wording while its document verifies", () => {
  refusedAt(".steps[1].current_quote", "evidence-changed", (chain) => {
    const step = chain.steps[1];
    if (step.kind === "stated") step.current_quote = null;
  });
  refusedAt(".steps[1].pinned_quote", "evidence-changed", (chain) => {
    const step = chain.steps[1];
    if (step.kind === "stated") step.pinned_quote = null;
  });
  refusedAt(".steps[1].state", "available", (chain) => {
    const step = chain.steps[1];
    if (step.kind === "stated") step.state = "record_changed";
  });
});

test("refuses a label that holds a digit beside a withheld source", () => {
  refusedAt(".steps[2].label", "withheld", (chain) => {
    const step = chain.steps[2];
    if (step.kind === "stated") step.label = "The cave reaches 80% of capacity";
  });
});

test("refuses an arrow character (→, ⟶, ->) in assistant text and served reasons, at its place", () => {
  for (const arrow of ["→", "⟶", "->"]) {
    const at = (place: string, name: string, change: (chain: ChainView) => void) => {
      refusedAt(place, name, change);
      assert.match(refusalOf(name, change) ?? "", /: holds an arrow character$/, `${place} ${arrow}`);
    };
    at(".title", "available", (chain) => { chain.title = `A ${arrow} B`; });
    at(".steps[0].label", "available", (chain) => {
      const step = chain.steps[0];
      if (step.kind === "stated") step.label = `A ${arrow} B`;
    });
    at(".steps[3].text", "available", (chain) => {
      const step = chain.steps[3];
      if (step.kind === "not_stated") step.text = `No retained source states A ${arrow} B`;
    });
    at(".steps[4].text", "available", (chain) => {
      const step = chain.steps[4];
      if (step.kind === "mechanism") step.text = `A ${arrow} B`;
    });
    at(".history.versions[0].title", "available", (chain) => { chain.history.versions[0].title = `A ${arrow} B`; });
    at(".history.versions[1].change.note", "two-versions", (chain) => {
      (chain.history.versions[1].change as Record<string, unknown>).note = `A ${arrow} B`;
    });
    at(".reasons[0]", "evidence-changed", (chain) => { chain.reasons[0] = `${chain.reasons[0]} ${arrow}`; });
    at(".steps[2].problem", "withheld", (chain) => {
      const step = chain.steps[2];
      if (step.kind === "stated") step.problem = `${step.problem} ${arrow}`;
    });
    at(".history.readings[0].differs[0]", "withheld", (chain) => {
      chain.history.readings[0].differs[0] = `${chain.history.readings[0].differs[0]} ${arrow}`;
    });
  }
});

test("reads an arrow in the owner's words and in source wording, which are never scanned for one", () => {
  const view = fixture("available");
  const chain = view.chains[0];
  chain.history.reviews[0].notes = "step 1 -> step 2";
  chain.history.readings[0].line = "Test line: step 1 → step 2.";
  chain.reading = copy(chain.history.readings[0]);
  const step = chain.steps[0];
  if (step.kind === "stated") step.quote = `${step.quote} -> and more`;
  chain.history.versions[0].passages[0].quote = "A pinned quote -> with an arrow.";
  (chain.event.current as Record<string, unknown>).kind = "Sales -> report";
  assert.equal(eventChainsRefusal(view), null);
  const changed = fixture("evidence-changed");
  const sides = changed.chains[0].steps[1];
  if (sides.kind === "stated") {
    sides.pinned_quote = `${sides.pinned_quote} ⟶ pinned`;
    sides.current_quote = `${sides.current_quote} -> current`;
  }
  changed.chains[0].history.reviews[1].notes = "Compare step 2 → step 3.";
  changed.chains[0].approval.notes = changed.chains[0].history.reviews[1].notes;
  assert.equal(eventChainsRefusal(changed), null);
});

test("checks a record's figures by the step count of the version it names", () => {
  const view = fixture("two-versions");
  const chain = view.chains[0];
  assert.deepEqual(chain.history.versions.map((item) => item.steps), [5, 4]);
  assert.equal(chain.steps.length, 4);
  const older = chain.history.readings[1];
  assert.equal(older.basis.chain.version, 1);
  assert.equal(older.masked, true);
  assert.equal(older.line, "Test line: the company expects [figure withheld] in [figure withheld], see step 5.");
  assert.equal(eventChainsRefusal(view), null);  // "step 5" names a step of version 1, so it is not a figure.
  // Read by the latest version's four steps, "5" would be a figure the server left unmasked.
  refusedAt(".history.readings[1].line", "two-versions", (one) => { one.history.versions[0].steps = 4; });
  refusedAt(".history.readings[1].basis.chain", "two-versions", (one) => {
    one.history.readings[1].basis.chain.version = 3;
  });
  refusedAt(".history.versions[1].steps", "two-versions", (one) => { one.history.versions[1].steps = 5; });
  refusedAt(".history.versions[0].steps", "two-versions", (one) => {
    (one.history.versions[0] as Record<string, unknown>).steps = "5";
  });
});

test("Hebrew step references take up to three prefix letters, as the server reads them", () => {
  const text = "ראו בשלב 2, ובשלב 3 ושבשלבים 4";
  assert.equal(maskedText(text, 4), text);
  assert.equal(maskedText("ראו בשלב 9", 4), "ראו בשלב [figure withheld]");
  assert.equal(maskedText("ושבכשלב 2", 4), "ושבכשלב [figure withheld]");  // Four prefix letters.
  assert.equal(maskedText("אבשלב 2", 4), "אבשלב [figure withheld]");  // Inside another word.
});

test("masks every text of the table as the server does", () => {
  // The same table is read by tests/test_event_chain_text.py: only the digits 0 to 9 make a figure or a step number.
  const table = JSON.parse(readFileSync(new URL("./fixtures/event-chain-masking.json", import.meta.url), "utf8"));
  const cases: { text: string; steps: number; masked: string }[] = table.cases;
  assert.ok(cases.length >= 15);
  for (const one of cases) assert.equal(maskedText(one.text, one.steps), one.masked, JSON.stringify(one.text));
});

test("reads a record whose basis fails when it holds \"see step ٠3\" as the server masks it", () => {
  // The server once kept the whole text (step 3 to it) while this reader saw a bare 3 and refused the page.
  const view = fixture("withheld");
  view.chains[0].history.reviews[0].notes = "see step ٠[figure withheld]";
  assert.equal(eventChainsRefusal(view), null);
  refusedAt(".history.reviews[0].notes", "withheld", (chain) => { chain.history.reviews[0].notes = "see step ٠3"; });
});

test("refuses the wrong version, a provider call and an extra field", () => {
  for (const change of [(v: Record<string, unknown>) => { v.view_version = "event-chains-view-0.2"; },
    (v: Record<string, unknown>) => { v.provider_called = true; }, (v: Record<string, unknown>) => { v.extra = 1; }]) {
    const view = fixture("available") as unknown as Record<string, unknown>;
    change(view);
    assert.notEqual(eventChainsRefusal(view), null);
  }
});

test("accepts an invalid history with a null approval and no records, and refuses a null approval otherwise", () => {
  const view = fixture("available");
  const chain = view.chains[0];
  chain.history.state = "invalid";
  chain.history.problem = "The saved review history is inconsistent";
  chain.history.reviews = [];
  chain.history.readings = [];
  chain.approval = { state: null, review_id: null, saved_at: null, account: null, notes: null, masked: null,
                     differs: [] };
  chain.reading = null;
  chain.binding.approval_id = chain.binding.parent_review_id = chain.binding.parent_reading_id = null;
  assert.equal(eventChainsRefusal(view), null);
  refusedAt(".approval", "available", (one) => {
    one.approval = { ...one.approval, state: null };
  });
});

// ---------------------------------------------------------------- the saves

type Call = { url: string; init: RequestInit };

async function withFetch<T>(fake: typeof fetch, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = fake;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}
const replying = (status: number, body: unknown, seen: Call[] = []) => (async (input: RequestInfo | URL,
  init?: RequestInit) => {
  seen.push({ url: String(input), init: init ?? {} });
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}) as typeof fetch;

const chainOf = (): ChainView => fixture("available").chains[0];
const without = (body: object) => Object.fromEntries(Object.entries(body).filter(([key]) => key !== "chain_sha256"));
const savedFrom = (chain: ChainView, sent: SentSave, sequence: number) => ({
  record_version: sent.kind === "reviews" ? "event-chain-review-0.1" : "event-chain-reading-0.1",
  chain_id: chain.id, sequence, ...without(sent.body),
  basis: { chain: { id: chain.id, sha256: sent.body.chain_sha256, version: 1 }, evidence_sha256: "a".repeat(64),
           thesis: chain.history.versions[0].thesis, documents: [] },
  account: { user_id: "local-operator", username: "operator" }, saved_at: "2026-11-11T09:00:00+00:00",
});

test("posts with the action and account headers", async () => {
  const chain = chainOf();
  bindAdminAccount("local-operator-id");
  const seen: Call[] = [];
  const sent: SentSave = { kind: "reviews", body: reviewBody(chain, "approved", "  Checked again.  ") };
  try {
    const result = await withFetch(replying(201, { record: savedFrom(chain, sent, 3) }, seen),
      () => saveReview(chain, "approved", "  Checked again.  "));
    assert.equal(result.state, "ready");
  } finally {
    bindAdminAccount(null);
  }
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, "/api/theses/copper/event-chains/synthetic-world-chain/reviews");
  assert.equal(seen[0].init.method, "POST");
  assert.deepEqual(seen[0].init.headers, { "Content-Type": "application/json", Accept: "application/json",
    [EVENT_CHAIN_HEADER]: "1", "X-Second-Order-Account": "local-operator-id" });
  assert.deepEqual(JSON.parse(String(seen[0].init.body)), {
    parent_review_id: chain.binding.parent_review_id, chain_sha256: chain.binding.chain_sha256,
    status: "approved", notes: "Checked again." });
  assert.deepEqual(Object.keys(JSON.parse(String(seen[0].init.body))),
    ["parent_review_id", "chain_sha256", "status", "notes"]);
  const reading = readingBody(chain, "neither", "not_sure", "A line.");
  assert.deepEqual(Object.keys(reading ?? {}),
    ["parent_reading_id", "chain_sha256", "approval_id", "short_term", "long_term", "line"]);
  const second: Call[] = [];
  await withFetch(replying(422, { detail: "no" }, second), () => saveReading(chain, "neither", "not_sure", "A line."));
  assert.equal(second[0].url, "/api/theses/copper/event-chains/synthetic-world-chain/readings");
  assert.deepEqual(second[0].init.headers, { "Content-Type": "application/json", Accept: "application/json",
    [EVENT_CHAIN_HEADER]: "1" });
});

test("maps 201, 409 (blocked) and 422 (failed), with 5xx and no reply unconfirmed", async () => {
  const chain = chainOf();
  const sent: SentSave = { kind: "reviews", body: reviewBody(chain, "needs_revision", "Fix step 3.") };
  const ok = savedFrom(chain, sent, 3);
  const run = (fake: typeof fetch) => withFetch(fake, () => saveReview(chain, "needs_revision", "Fix step 3."));
  assert.deepEqual(await run(replying(201, { record: ok })), { state: "ready", status: 201, data: { record: ok } });
  assert.deepEqual(await run(replying(409, { detail: "Another record was saved", latest: "f".repeat(64) })),
    { state: "blocked", message: "Another record was saved", latest: "f".repeat(64) });
  assert.deepEqual(await run(replying(409, { detail: "Another record was saved", latest: null })),
    { state: "blocked", message: "Another record was saved", latest: null });
  assert.deepEqual(await run(replying(422, { detail: "The notes are too long" })),
    { state: "failed", message: "The notes are too long" });
  assert.deepEqual(await run(replying(404, { detail: "No event chain has this id" })),
    { state: "failed", message: "No event chain has this id" });
  for (const status of [401, 403, 428]) {
    const out = await run(replying(status, { contract: "x", code: "account_binding_required", detail: "Sign in again" }));
    assert.deepEqual(out, { state: "failed", message: "Sign in again" }, String(status));
  }
  assert.equal((await run(replying(500, { detail: "The local records could not be written" }))).state, "unconfirmed");
  assert.equal((await run((async () => { throw new TypeError("network"); }) as typeof fetch)).state, "unconfirmed");
  // A 201 whose record is not the one that was sent proves nothing.
  assert.equal((await run(replying(201, { record: { ...ok, notes: "Other." } }))).state, "unconfirmed");
  assert.equal((await run(replying(201, { record: { ...ok, chain_id: "other" } }))).state, "unconfirmed");
  assert.equal((await run(replying(200, { record: ok }))).state, "unconfirmed");
  // A reading without a current approval is not sent at all.
  const none: Call[] = [];
  const unbound = copy(chain);
  unbound.binding.approval_id = null;
  const refused = await withFetch(replying(201, {}, none), () => saveReading(unbound, "neither", "neither", "x"));
  assert.equal(refused.state, "failed");
  assert.equal(none.length, 0);
});

test("fetches the view and reads it fail-closed", async () => {
  const seen: Call[] = [];
  const loaded = await withFetch(replying(200, fixture("available"), seen), () => fetchEventChains());
  assert.equal(loaded.state, "ready");
  assert.equal(seen[0].url, "/api/theses/copper/event-chains");
  assert.equal((await withFetch(replying(503, { detail: "No thesis" }), () => fetchEventChains())).state, "error");
  const bad = fixture("available");
  bad.chains[0].reasons = ["A reason that does not belong."];
  assert.equal((await withFetch(replying(200, bad), () => fetchEventChains())).state, "error");
  const down = await withFetch((async () => { throw new TypeError("refused"); }) as typeof fetch,
    () => fetchEventChains());
  assert.equal(down.state, "error");
});

// ---------------------------------------------------------------- settling a lost reply

test("settles a lost save from the history without sending again", async () => {
  const chain = chainOf();
  const seen: Call[] = [];
  const lost = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: String(input), init: init ?? {} });
    throw new TypeError("connection lost");
  }) as typeof fetch;
  const result = await withFetch(lost, () => saveReading(chain, "refutes", "supports", "A new line, see step 2."));
  assert.equal(result.state, "unconfirmed");
  const sent: SentSave = { kind: "readings", body: readingBody(chain, "refutes", "supports", "A new line, see step 2.")! };
  // The reply came back with the next history: the record is there. Settling reads only.
  const next = copy(chain.history);
  const saved = copy(next.readings[0]);
  Object.assign(saved, { ...without(sent.body), reading_id: "b".repeat(64), sequence: 2,
    parent_reading_id: next.readings[0].reading_id });
  next.readings.push(saved);
  const count = seen.length;
  await withFetch(replying(500, {}, seen), async () => {
    assert.equal(settle(next, sent), "saved");
    assert.equal(settle(chain.history, sent), "not-saved");
  });
  assert.equal(count, 1);
  assert.equal(seen.length, 1);  // Exactly one POST; settling never sends.
});

test("settles saved, superseded, conflict and not-saved", () => {
  const chain = chainOf();
  const history = chain.history;
  const sent: SentSave = { kind: "readings", body: readingBody(chain, "supports", "supports", "Our line.")! };
  const ours = (parent: string | null, sequence: number, id: string) => ({
    ...copy(history.readings[0]), reading_id: id, parent_reading_id: parent, sequence, short_term: "supports" as const,
    long_term: "supports" as const, line: "Our line.", approval_id: chain.binding.approval_id!,
  });
  const parent = history.readings[0].reading_id;
  const first = ours(parent, 2, "c".repeat(64));
  const withOurs = { ...history, readings: [history.readings[0], first] };
  assert.equal(settle(withOurs, sent), "saved");
  assert.equal(settle(history, sent), "not-saved");
  const later = ours(first.reading_id, 3, "d".repeat(64));
  assert.equal(settle({ ...history, readings: [history.readings[0], first, later] }, sent), "superseded");
  // A competing tab saved a different line from the same parent: conflict, never saved.
  const theirs = { ...first, line: "Their line." };
  assert.equal(settle({ ...history, readings: [history.readings[0], theirs] }, sent), "conflict");
  assert.equal(settle({ ...history, readings: [history.readings[0], { ...first, short_term: "refutes" as const }] },
    sent), "conflict");
  assert.equal(settle({ ...history, readings: [history.readings[0], { ...first, approval_id: "e".repeat(64) }] },
    sent), "conflict");
  // A first save has a null parent.
  const firstSent: SentSave = { kind: "reviews", body: { ...reviewBody(chain, "approved", "Checked."),
    parent_review_id: null } as ReviewBody };
  const firstReview = { ...copy(history.reviews[0]), parent_review_id: null, status: "approved" as const,
    notes: "Checked." };
  assert.equal(settle({ ...history, reviews: [firstReview] }, firstSent), "saved");
  assert.equal(settle({ ...history, reviews: [] }, firstSent), "not-saved");
  // Masked saved text is the sent text with its figures withheld, not a conflict.
  const maskedSent: SentSave = { kind: "reviews", body: { ...(firstSent.body as ReviewBody),
    notes: "It is 85% by step 3." } };
  const masked = { ...firstReview, masked: true, notes: "It is [figure withheld] by step 3." };
  assert.equal(settle({ ...history, reviews: [masked] }, maskedSent), "saved");
});

test("settle never uses the parent alone", () => {
  const chain = chainOf();
  const sent: SentSave = { kind: "readings", body: readingBody(chain, "supports", "supports", "Our line.")! };
  const parent = chain.history.readings[0].reading_id;
  const other = { ...copy(chain.history.readings[0]), reading_id: "c".repeat(64), parent_reading_id: parent,
    sequence: 2, short_term: "supports" as const, long_term: "supports" as const, line: "Our line.",
    approval_id: chain.binding.approval_id!,
    basis: { ...chain.history.readings[0].basis,
             chain: { ...chain.history.readings[0].basis.chain, sha256: "9".repeat(64) } } };
  const history = { ...chain.history, readings: [chain.history.readings[0], other] };
  assert.equal(settle(history, sent), "conflict");
  assert.equal(settle({ ...history, readings: [history.readings[0], { ...other,
    basis: chain.history.readings[0].basis }] }, sent), "saved");
  const review: SentSave = { kind: "reviews", body: reviewBody(chain, "approved", "Same text.") };
  const rival = { ...copy(chain.history.reviews[1]), parent_review_id: chain.history.reviews[0].review_id,
    status: "approved" as const, notes: "Same text.",
    basis: { ...chain.history.reviews[1].basis, chain: { ...chain.history.reviews[1].basis.chain, sha256: "8".repeat(64) } } };
  assert.equal(settle({ ...chain.history, reviews: [chain.history.reviews[0], rival] },
    { kind: "reviews", body: { ...review.body, parent_review_id: chain.history.reviews[0].review_id } }), "conflict");
});

test("settles a masked record whose figures the server masked by the real step count", () => {
  const chain = chainOf();
  assert.equal(chain.steps.length, 5);
  const sent: SentSave = { kind: "reviews", body: { ...reviewBody(chain, "approved", "see step 9 and 85%"),
    parent_review_id: null } };
  const record = { ...copy(chain.history.reviews[0]), parent_review_id: null, status: "approved" as const,
    masked: true, notes: "see step [figure withheld] and [figure withheld]" };
  assert.equal(maskedText("see step 9 and 85%", 5), record.notes);
  assert.equal(settle({ ...chain.history, reviews: [record] }, sent), "saved");
  const other = { ...record, notes: "see step [figure withheld] but [figure withheld]" };
  assert.equal(settle({ ...chain.history, reviews: [other] }, sent), "conflict");
  const unmasked = { ...record, masked: false };
  assert.equal(settle({ ...chain.history, reviews: [unmasked] }, sent), "conflict");
});

test("an invalid history settles as unverifiable and nothing is sent", async () => {
  const chain = chainOf();
  const seen: Call[] = [];
  const sent: SentSave = { kind: "readings", body: readingBody(chain, "supports", "supports", "Our line.")! };
  const invalid = { ...chain.history, state: "invalid" as const, problem: "inconsistent", reviews: [], readings: [] };
  await withFetch(replying(500, {}, seen), async () => {
    assert.equal(settle(invalid, sent), "unverifiable");
  });
  assert.equal(seen.length, 0);
});

void ({} as ReadingBody);
