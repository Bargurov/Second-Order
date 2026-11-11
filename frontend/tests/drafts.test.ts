// Draft review logic, read from views captured from the real preparation of synthetic saved attempts
// (see tests/test_draft_views.py): a draft, a decline, an invalid response and a technical failure.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { DRAFT_VIEW_VERSION, VIEW_HASH_HEADER, VIEW_VERSION, fetchDraft, fetchDrafts } from "../src/api.ts";
import type { DraftIndex, DraftReviewView } from "../src/draftTypes.ts";
import {
  OUTCOME_INFO, REVIEW_CHECKLIST, REVIEW_STATUS, draftRows, legRows, requestedDraft, viewProblems,
} from "../src/drafts.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8")) as T;
const view = (kind: string) => load<DraftReviewView>(`draft-${kind}.json`);
const KINDS = ["draft", "no-draft", "invalid", "technical-failure"];

test("the captured draft views carry their own contract version, separate from Dossiers", () => {
  assert.equal(load<DraftIndex>("drafts-index.json").view_version, DRAFT_VIEW_VERSION);
  assert.notEqual(DRAFT_VIEW_VERSION, VIEW_VERSION);
  for (const kind of KINDS) {
    assert.equal(view(kind).view_version, DRAFT_VIEW_VERSION, kind);
    assert.equal(view(kind).review_status, REVIEW_STATUS, kind);
    assert.deepEqual(viewProblems(view(kind)), [], kind);
  }
  assert.equal(REVIEW_STATUS, "Not frozen · Requires human review");
});

test("a draft view has no freeze time, evaluation, chart, ranking, thinking or raw record", () => {
  const forbidden = ["frozen_at", "replay_as_of", "evaluation", "verdict", "percentile_rank", "series", "reference",
                     "thinking", "signature", "system", "headers", "usage"];
  const keys = (value: unknown): string[] =>
    Array.isArray(value) ? value.flatMap(keys)
      : value && typeof value === "object" ? Object.entries(value).flatMap(([key, item]) => [key, ...keys(item)]) : [];
  for (const kind of KINDS) {
    const found = keys(view(kind)).filter((key) => forbidden.includes(key));
    assert.deepEqual(found, [], kind);
  }
});

test("a refusal is a 'No draft' with the model's words, distinct from invalid responses and failures", () => {
  const labels = Object.fromEntries(KINDS.map((kind) => [kind, OUTCOME_INFO[view(kind).outcome].label]));
  assert.deepEqual(labels, { draft: "Draft", "no-draft": "No draft", invalid: "Invalid response",
                             "technical-failure": "Technical failure" });
  assert.equal(new Set(Object.values(OUTCOME_INFO).map((info) => info.className)).size, 4);
  const declined = view("no-draft");
  assert.equal(declined.draft, null);
  assert.match(declined.explanation?.text[0] ?? "", /^No hypothesis: the source does not say/);
  for (const kind of ["invalid", "technical-failure"]) {
    assert.equal(view(kind).draft, null);
    assert.equal(view(kind).explanation, null);
    assert.equal(typeof view(kind).problem, "string");
  }
});

test("no wording claims that structure checks verify reasoning or that a model statement is a fact", () => {
  for (const info of Object.values(OUTCOME_INFO)) {
    assert.doesNotMatch(info.meaning, /verified|correct|accurate|true\b|confirmed/i);
  }
  assert.match(OUTCOME_INFO.draft.meaning, /says nothing about whether its reasoning is sound/);
  const rows = legRows(view("draft").draft!);
  assert.deepEqual(rows.map((row) => [row.role, row.observable, row.direction, row.link]),
                   [["Primary", "yield:ust2y_cmt", "Down", "Direct"], ["Secondary", "yield:ust10y_cmt", "Down", "Proxy"]]);
  assert.equal(rows[0].horizon, "5 observations after the scoring anchor");
  assert.match(rows[0].reportsMove, /per the model/);  // The flag is attributed to the model, not asserted.
});

test("the checklist is short and generic", () => {
  assert.deepEqual(REVIEW_CHECKLIST.map((item) => item.topic),
                   ["Source support", "Unsupported assumptions", "Distinct channels", "Already-reported moves"]);
  const text = JSON.stringify(REVIEW_CHECKLIST);
  assert.doesNotMatch(text, /pilot|sonnet|opus|clear-policy|conflicting|ambiguous|headline-reports|prompt-[0-9]/i);
});

test("an inconsistent view is refused rather than repaired", () => {
  const base = view("draft");
  const broken: [string, DraftReviewView][] = [
    ["no status", { ...base, review_status: "Reviewed" }],
    ["draft missing", { ...base, draft: null }],
    ["decline with a draft", { ...view("draft"), outcome: "no_draft" }],
    ["failure without a problem", { ...view("technical-failure"), problem: null }],
    ["leg on a channel node", { ...base, draft: { ...base.draft!, legs: base.draft!.legs.map((leg, i) =>
      i === 0 ? { ...leg, node_id: "policy" } : leg) } }],
    ["two primaries", { ...base, draft: { ...base.draft!, legs: base.draft!.legs.map((leg) => ({ ...leg, primary: true })) } }],
    ["dangling edge", { ...base, draft: { ...base.draft!, edges: [...base.draft!.edges, { source: "x", target: "two" }] } }],
  ];
  for (const [name, candidate] of broken) assert.notDeepEqual(viewProblems(candidate), [], name);
});

test("the ?draft= selection accepts only a well-formed ID and the list is newest first", () => {
  const id = view("draft").id;
  assert.equal(requestedDraft(`?draft=${id}`), id);
  for (const search of ["", "?draft=", "?draft=../index", `?draft=${id.toUpperCase()}`, "?draft=%E0%A4"]) {
    assert.equal(requestedDraft(search), null, search);
  }
  const index = load<DraftIndex>("drafts-index.json");
  const later = { ...index.drafts[0], id: "f".repeat(64), sent_at: "2026-10-01T00:00:00+00:00" };
  assert.equal(draftRows({ ...index, drafts: [...index.drafts, later] })[0].id, "f".repeat(64));
  assert.equal(draftRows(index).length, 4);
});

test("draft requests map to loading outcomes: ready, not prepared, missing and error", async () => {
  const original = globalThis.fetch;
  const reply = (status: number, body: unknown) => async () =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json",
                                                            [VIEW_HASH_HEADER]: "b".repeat(64) } });
  const index = load<DraftIndex>("drafts-index.json");
  const cases: [string, typeof fetch, string][] = [
    ["ready", reply(200, index) as typeof fetch, "ready"],
    ["not prepared", reply(503, { detail: "Drafts for review have not been prepared." }) as typeof fetch, "not-prepared"],
    ["unknown ID", reply(404, { detail: "Unknown draft ID" }) as typeof fetch, "missing"],
    ["Dossier contract sent instead", reply(200, { ...index, view_version: VIEW_VERSION }) as typeof fetch, "error"],
    ["server unreachable", (async () => { throw new TypeError("network"); }) as typeof fetch, "error"],
  ];
  try {
    for (const [name, fake, state] of cases) {
      globalThis.fetch = fake;
      const signal = new AbortController().signal;
      assert.equal((await fetchDrafts(signal)).state, state, name);
      assert.equal((await fetchDraft("a".repeat(64), signal)).state, state === "ready" ? "ready" : state, name);
    }
  } finally {
    globalThis.fetch = original;
  }
});
