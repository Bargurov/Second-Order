// Human review logic over the captured synthetic draft views (see tests/test_draft_views.py). A review is the
// reviewer's own record: it never changes the model's proposal, and its status is human judgment only.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  REVIEW_HISTORY_VERSION, REVIEW_RECORD_VERSION, VIEW_HASH_HEADER, fetchDraft, fetchReviews, saveReview,
} from "../src/api.ts";
import type { DraftReviewView, ReviewHistory, ReviewPayload, ReviewRecord } from "../src/draftTypes.ts";
import { guardLeaving, mayLeave } from "../src/leave.ts";
import {
  MAX_NOTES, NO_STATUS_LABEL, STATUS_LABEL, STATUS_NOTE, appendSaved, correctionCount, correctionRows,
  correctionsFrom, currentReview, formFrom, formProblems, historyUpTo, isDirty, isEmptyReview, payloadFrom, reconcile,
} from "../src/review.ts";

const view = (kind: string): DraftReviewView =>
  JSON.parse(readFileSync(new URL(`./fixtures/draft-${kind}.json`, import.meta.url), "utf-8")) as DraftReviewView;

const LOADED = "b".repeat(64);  // The fingerprint served with the view the page loaded.
const EARLIER = "e".repeat(64);  // The fingerprint of a view prepared before it.

function record(draft: DraftReviewView, changes: Partial<ReviewRecord> = {}): ReviewRecord {
  return {
    record_version: REVIEW_RECORD_VERSION, review_id: "a".repeat(64), draft_id: draft.id, sequence: 1,
    parent_review_id: null, saved_at: "2026-10-04T12:00:00+00:00", attributed_to: "local human reviewer",
    status: "needs_revision", notes: "Saved note.", corrections: { summary: null, legs: {} },
    binding: { draft_view_sha256: LOADED, draft_view_version: draft.view_version, outcome: draft.outcome,
               prompt_hash: draft.provenance.prompt_hash, response_sha256: draft.provenance.response_sha256,
               request_id: draft.provenance.request_id, pilot: draft.provenance.pilot, case: draft.provenance.case },
    ...changes,
  };
}

const historyOf = (draft: DraftReviewView, reviews: ReviewRecord[], fingerprint = LOADED): ReviewHistory =>
  ({ view_version: REVIEW_HISTORY_VERSION, draft_id: draft.id, draft_view_sha256: fingerprint, reviews });

/** The version the server would write for `sent`, as version `sequence`. */
const recorded = (draft: DraftReviewView, sent: ReviewPayload, sequence: number, id: string): ReviewRecord =>
  record(draft, { review_id: id, sequence, parent_review_id: sent.parent_review_id, status: sent.status,
                  notes: sent.notes, corrections: sent.corrections });

test("a reviewer starts from the model's proposal, or from the latest saved version over it", () => {
  const draft = view("draft");
  const fresh = formFrom(draft, null);
  assert.equal(fresh.summary, draft.draft!.summary);
  assert.equal(fresh.status, null);
  assert.equal(isDirty(draft, fresh, null), false);
  const saved = record(draft, { corrections: { summary: "Corrected summary.", legs: { primary: { falsifier: "Corrected." } } } });
  const resumed = formFrom(draft, saved);
  assert.equal(resumed.summary, "Corrected summary.");
  assert.equal(resumed.legs.primary.falsifier, "Corrected.");
  assert.equal(resumed.legs.primary.rationale, draft.draft!.legs[0].rationale);
  assert.equal(isDirty(draft, resumed, saved), false);
});

test("only real changes become corrections, and putting text back removes the correction", () => {
  const draft = view("draft");
  const form = formFrom(draft, null);
  form.summary = `  ${draft.draft!.summary}  `;  // Whitespace only: not a correction.
  form.legs.primary = { ...form.legs.primary, headline_reports_move: true, rationale: "  New reasoning.  " };
  assert.deepEqual(correctionsFrom(draft, form),
                   { summary: null, legs: { primary: { rationale: "New reasoning.", headline_reports_move: true } } });
  assert.equal(isDirty(draft, form, null), true);
  form.legs.primary = { ...form.legs.primary, headline_reports_move: false, rationale: draft.draft!.legs[0].rationale };
  assert.deepEqual(correctionsFrom(draft, form), { summary: null, legs: {} });
  assert.equal(isDirty(draft, form, null), false);
  form.status = "human_reviewed";
  assert.equal(isDirty(draft, form, null), true);
});

test("the payload binds to the view's hashes and names its parent; the server stamps the rest", () => {
  const draft = view("draft");
  const saved = record(draft);
  const form = { ...formFrom(draft, saved), notes: "Second thoughts." };
  const payload = payloadFrom(draft, LOADED, form, saved);
  assert.deepEqual(Object.keys(payload).sort(), ["binding", "corrections", "notes", "parent_review_id", "status"]);
  assert.equal(payload.parent_review_id, saved.review_id);
  assert.deepEqual(payload.binding, { draft_view_sha256: LOADED, prompt_hash: draft.provenance.prompt_hash,
                                      response_sha256: draft.provenance.response_sha256 });
  assert.equal(payloadFrom(draft, LOADED, formFrom(draft, null), null).parent_review_id, null);
});

test("a version saved against an earlier view is never applied, but the next save still follows it", () => {
  const draft = view("draft");
  const earlier = record(draft, {
    status: "human_reviewed", binding: { ...record(draft).binding, draft_view_sha256: EARLIER },
    corrections: { summary: "Corrected for the earlier view.", legs: {} },
  });
  const history = historyOf(draft, [earlier]);
  assert.equal(currentReview(history, LOADED), null);
  assert.equal(currentReview(historyOf(draft, [record(draft)]), LOADED)?.review_id, "a".repeat(64));
  const form = formFrom(draft, currentReview(history, LOADED));
  assert.equal(form.summary, draft.draft!.summary);  // The earlier correction is not applied...
  assert.equal(form.status, null);  // ...nor is the earlier judgment treated as current.
  assert.equal(isDirty(draft, form, currentReview(history, LOADED)), false);
  assert.equal(payloadFrom(draft, LOADED, { ...form, notes: "Again." }, earlier).parent_review_id, earlier.review_id);
});

test("a confirmed save is appended only when the reply is the next version of what was sent", () => {
  const draft = view("draft");
  const first = record(draft);
  const sent = payloadFrom(draft, LOADED, { ...formFrom(draft, first), notes: "Second." }, first);
  const reply = recorded(draft, sent, 2, "c".repeat(64));
  assert.deepEqual(appendSaved(historyOf(draft, [first]), sent, reply)?.reviews, [first, reply]);
  const wrong: [string, ReviewRecord][] = [
    ["another sequence", { ...reply, sequence: 3 }], ["another parent", { ...reply, parent_review_id: null }],
    ["other notes", { ...reply, notes: "Something else." }], ["another draft", { ...reply, draft_id: "f".repeat(64) }],
    ["another view", { ...reply, binding: { ...reply.binding, draft_view_sha256: EARLIER } }],
  ];
  for (const [name, bad] of wrong) assert.equal(appendSaved(historyOf(draft, [first]), sent, bad), null, name);
});

test("an unconfirmed save is settled from the saved versions alone", () => {
  const draft = view("draft");
  const first = record(draft);
  const sent = payloadFrom(draft, LOADED, { ...formFrom(draft, first), notes: "Lost reply." }, first);
  const ours = recorded(draft, sent, 2, "c".repeat(64));
  const theirs = { ...ours, review_id: "d".repeat(64), notes: "Saved in another tab." };
  const later = record(draft, { review_id: "9".repeat(64), sequence: 3, parent_review_id: ours.review_id });
  assert.deepEqual(reconcile(historyOf(draft, [first, ours]), sent), { state: "saved", record: ours });
  assert.deepEqual(reconcile(historyOf(draft, [first]), sent), { state: "not-saved" });
  // Recorded, then followed by a newer version: saved, not refused, and the newer one is named.
  const newer = historyOf(draft, [first, ours, later]);
  assert.deepEqual(reconcile(newer, sent), { state: "superseded", record: ours, latest: later });
  assert.deepEqual(historyUpTo(newer, ours).reviews, [first, ours]);
  const other = reconcile(historyOf(draft, [first, theirs]), sent);
  assert.match(other.state === "conflict" ? other.message : "", /different version 2 .* yours was not saved/);
  const firstSave = payloadFrom(draft, LOADED, { ...formFrom(draft, null), notes: "First." }, null);
  assert.deepEqual(reconcile(historyOf(draft, []), firstSave), { state: "not-saved" });
  assert.equal(reconcile(historyOf(draft, [recorded(draft, firstSave, 1, "c".repeat(64))]), firstSave).state, "saved");
});

test("declines and failures take notes and a judgment, never corrections", () => {
  for (const kind of ["no-draft", "invalid", "technical-failure"]) {
    const attempt = view(kind);
    const form = { ...formFrom(attempt, null), notes: "Declining was right.", status: "human_reviewed" as const };
    assert.deepEqual(form.legs, {}, kind);
    assert.deepEqual(payloadFrom(attempt, LOADED, form, null).corrections, { summary: null, legs: {} }, kind);
    assert.deepEqual(correctionRows(attempt, record(attempt)), [], kind);
  }
});

test("empty, unchanged and over-long reviews cannot be saved", () => {
  const draft = view("draft");
  const empty = payloadFrom(draft, LOADED, formFrom(draft, null), null);
  assert.equal(isEmptyReview(empty), true);
  const form = formFrom(draft, null);
  form.summary = "   ";
  assert.match(formProblems(draft, form).join(" "), /The summary cannot be empty/);
  assert.match(formProblems(draft, { ...formFrom(draft, null), notes: "x".repeat(MAX_NOTES + 1) }).join(" "), /limited/);
  assert.deepEqual(formProblems(draft, formFrom(draft, null)), []);
});

test("saved corrections are shown beside the model's original and counted per field", () => {
  const draft = view("draft");
  const saved = record(draft, { corrections: { summary: "Human summary.", legs: { secondary: { headline_reports_move: true } } } });
  const rows = correctionRows(draft, saved);
  assert.deepEqual(rows.map((row) => row.field), ["Summary", "Secondary leg · 10-year Treasury yield · move already reported?"]);
  assert.deepEqual(rows.map((row) => [row.original, row.corrected]),
                   [[draft.draft!.summary, "Human summary."], ["No", "Yes, the source reports this move"]]);
  assert.equal(correctionCount(saved.corrections), 2);
});

test("judgment labels describe human judgment, not verified reasoning or research eligibility", () => {
  assert.deepEqual(STATUS_LABEL, { needs_revision: "Needs revision", human_reviewed: "Human-reviewed" });
  assert.equal(NO_STATUS_LABEL, "No judgment recorded");
  assert.match(STATUS_NOTE, /record your judgment/);
  assert.match(STATUS_NOTE, /do not verify the model's reasoning, make a draft eligible for research/);
});

test("a save is one same-origin JSON POST, and each response becomes a distinct state", async () => {
  const draft = view("draft");
  const payload: ReviewPayload = payloadFrom(draft, LOADED, { ...formFrom(draft, null), notes: "Note." }, null);
  const original = globalThis.fetch;
  const sent: { url: string; init: RequestInit }[] = [];
  const reply = (status: number, body: unknown) => (async (url: string, init: RequestInit) => {
    sent.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  const cases: [string, typeof fetch, string][] = [
    ["created", reply(201, record(draft)), "saved"],
    ["created with an unreadable reply", reply(201, { ...record(draft), record_version: "other" }), "unconfirmed"],
    ["stale parent", reply(409, { detail: "Another review version was saved since this draft was loaded" }), "conflict"],
    ["view changed", reply(409, { detail: "The prepared draft has changed since it was loaded" }), "conflict"],
    ["nothing changed", reply(422, { detail: "Nothing changed since the last saved version" }), "invalid"],
    ["too large", reply(413, { detail: "A review is limited to 65536 bytes" }), "invalid"],
    ["unknown draft", reply(404, { detail: "Unknown draft ID" }), "invalid"],
    ["cross-origin refusal", reply(403, { detail: "Reviews are saved only from this server's own page" }), "refused"],
    ["server failure", reply(500, { detail: "The saved review history is inconsistent" }), "unconfirmed"],
    ["reply lost", (async () => { throw new TypeError("network"); }) as typeof fetch, "unconfirmed"],
  ];
  try {
    for (const [name, fake, state] of cases) {
      globalThis.fetch = fake;
      const result = await saveReview(draft.id, payload);
      assert.equal(result.state, state, name);
      if (result.state !== "saved") assert.ok(result.message.length > 0, name);
      // A lost or unreadable reply proves nothing either way, so no message claims that nothing was saved.
      if (result.state === "unconfirmed") assert.doesNotMatch(result.message, /nothing was saved/i, name);
    }
    assert.equal(sent.length, cases.length - 1);  // One request per save; nothing is sent again.
    const { url, init } = sent[0];
    assert.equal(url, `/api/drafts/${draft.id}/reviews`);
    assert.equal(init.method, "POST");
    assert.deepEqual(init.headers, { "Content-Type": "application/json", Accept: "application/json",
                                     "X-Second-Order-Review": "1" });
    assert.deepEqual(JSON.parse(String(init.body)), payload);
    globalThis.fetch = reply(200, historyOf(draft, [record(draft)]));
    assert.equal((await fetchReviews(draft.id, new AbortController().signal)).state, "ready");
    globalThis.fetch = reply(200, { view_version: "draft-review-history-0.1", draft_id: draft.id, reviews: [] });
    assert.equal((await fetchReviews(draft.id, new AbortController().signal)).state, "error");
  } finally {
    globalThis.fetch = original;
  }
});

test("a draft is loaded with the fingerprint served with it, or not at all", async () => {
  const draft = view("draft");
  const original = globalThis.fetch;
  const serve = (headers: Record<string, string>) => (async () => new Response(JSON.stringify(draft), {
    status: 200, headers: { "content-type": "application/json", ...headers } })) as typeof fetch;
  try {
    globalThis.fetch = serve({ [VIEW_HASH_HEADER]: LOADED });
    const loaded = await fetchDraft(draft.id, new AbortController().signal);
    assert.deepEqual(loaded, { state: "ready", data: { view: draft, fingerprint: LOADED } });
    for (const headers of [{}, { [VIEW_HASH_HEADER]: "not-a-hash" }]) {
      globalThis.fetch = serve(headers);
      assert.equal((await fetchDraft(draft.id, new AbortController().signal)).state, "error");
    }
  } finally {
    globalThis.fetch = original;
  }
});

test("leaving asks each registered page and stays on the first no", () => {
  const asked: string[] = [];
  const answer = (reply: boolean) => (question: string) => {
    asked.push(question);
    return reply;
  };
  assert.equal(mayLeave("/method", answer(false)), true);  // Nothing registered: nothing asked.
  let unsaved = true;
  const remove = guardLeaving((pathname) => (unsaved && pathname !== "/" ? "Discard?" : null));
  try {
    assert.equal(mayLeave("/", answer(false)), true);  // Staying on the Tracker never asks.
    assert.equal(mayLeave("/method", answer(false)), false);
    assert.equal(mayLeave("/h/abc", answer(true)), true);
    assert.deepEqual(asked, ["Discard?", "Discard?"]);
    unsaved = false;
    assert.equal(mayLeave("/method", answer(false)), true);
  } finally {
    remove();
  }
  unsaved = true;
  assert.equal(mayLeave("/method", answer(false)), true);  // Removed with its page.
  assert.equal(asked.length, 2);
});
