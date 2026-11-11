// Same-account recovery of unsaved work across a session expiry (src/client/recovery.ts), in this tab's memory only:
// drafts are held under the user's stable user_id, given back once and only to that user, discarded for anyone else
// and on an explicit sign-out; a review goes back into its editor only for the same analysis and result fingerprint,
// and still follows the version it was written after, so the server's review-conflict check applies. The drafts hold
// no password, and nothing here saves, quotes or runs. Page rules only, against the SYNTHETIC fixtures.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { Analysis } from "../src/contracts/user.ts";
import {
  SOURCE_KEY, admit, claim, discard, draftText, hold, holding, reviewKey, reviewRestore, toHold, type Recoverable,
} from "../src/client/recovery.ts";
import { reviewForm } from "../src/client/reviewDraft.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const recorded = load<{ analysis: Analysis }>("user-contract-analysis-recorded").analysis;
const A = "u-5ca1ab1e0000a001";
const B = "u-5ca1ab1e0000a002";
const source: Recoverable = { kind: "source", fields: { headline: "SYNTHETIC headline", source_url: "https://example.org/s",
  date: "2026-10-13", time: "10:00", offset: "+03:00", text: "SYNTHETIC source text typed before the session ended." } };
const review: Recoverable = { kind: "review", analysisId: recorded.analysis_id, headline: recorded.source.headline,
  resultSha256: recorded.result_sha256!, base: recorded.reviews.at(-1)!.review_id, status: "needs_revision",
  notes: "SYNTHETIC notes typed before the session ended." };
const drafts = { [SOURCE_KEY]: source, [reviewKey(recorded.analysis_id)]: review };

test("held drafts go back once, and only to the same user", () => {
  hold(A, drafts);
  assert.equal(holding(), A);
  assert.equal(admit(A), true);  // The same user signing in keeps them until a read confirms who it is.
  assert.deepEqual(claim(A), drafts);
  assert.deepEqual(claim(A), {});  // Once: a second claim finds nothing.
  assert.equal(holding(), null);
});

test("another user's sign-in discards the drafts unseen, so the first user cannot get them back either", () => {
  hold(A, drafts);
  assert.equal(admit(B), false);
  assert.equal(holding(), null);
  assert.deepEqual(claim(B), {});
  assert.deepEqual(claim(A), {});
  hold(A, drafts);
  assert.deepEqual(claim(B), {});  // A claim by anyone else empties the store as well.
  assert.deepEqual(claim(A), {});
});

test("an explicit sign-out discards them; holding nothing holds nothing", () => {
  hold(A, drafts);
  discard();
  assert.deepEqual([holding(), claim(A)], [null, {}]);
  hold(A, {});
  assert.equal(holding(), null);
});

test("at expiry, what is open now wins over a recovered draft for the same page; one not reopened is kept", () => {
  const live = new Map<string, Recoverable>([[reviewKey(recorded.analysis_id), { ...review, notes: "Edited again." }]]);
  const held = toHold(live, drafts);
  assert.deepEqual(Object.keys(held).sort(), [SOURCE_KEY, reviewKey(recorded.analysis_id)].sort());
  assert.equal((held[reviewKey(recorded.analysis_id)] as { notes: string }).notes, "Edited again.");
  assert.deepEqual(held[SOURCE_KEY], source);
});

test("a review goes back into its editor only for the same analysis and result; otherwise it is stale", () => {
  assert.equal(reviewRestore(review, recorded), "restore");
  assert.equal(reviewRestore(review, { ...recorded, result_sha256: "0".repeat(64) }), "stale");
  assert.equal(reviewRestore(review, { ...recorded, analysis_id: `${recorded.analysis_id}.other` }), "stale");
});

test("a restored review still follows the version it was written after, so the server can refuse a conflict", () => {
  const later = { ...recorded, reviews: [...recorded.reviews, { ...recorded.reviews[0], review_id: "r-later000000", sequence: 2,
    parent_review_id: recorded.reviews[0].review_id }] };
  const draft = { status: "needs_revision" as const, notes: "SYNTHETIC" };
  assert.equal(reviewForm(later, draft, (review as { base: string }).base).parent_review_id, recorded.reviews[0].review_id);
  assert.equal(reviewForm(later, draft).parent_review_id, "r-later000000");  // Without one, the version shown.
  assert.equal(reviewForm(later, draft, null).parent_review_id, null);  // Written before any version existed.
});

test("drafts hold the form's fields only: no password, and the copy text is what was typed", () => {
  const keys = new Set(Object.values(drafts).flatMap((draft) => [...Object.keys(draft),
    ...(draft.kind === "source" ? Object.keys(draft.fields) : [])]));
  assert.deepEqual([...keys].sort(), ["analysisId", "base", "date", "fields", "headline", "kind", "notes", "offset",
    "resultSha256", "source_url", "status", "text", "time"].sort());
  assert.doesNotMatch(JSON.stringify(drafts), /password/i);
  assert.equal(draftText(source), "SYNTHETIC headline\n\nhttps://example.org/s\n\nSYNTHETIC source text typed before the session ended.");
  assert.equal(draftText(review), "SYNTHETIC notes typed before the session ended.");
  assert.equal(draftText({ ...review, notes: "" } as Recoverable), "Needs revision");
});
