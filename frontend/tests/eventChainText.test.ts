import assert from "node:assert/strict";
import { test } from "node:test";
import { EVENT_GONE, eventLines, mechanismMark, priceChanges, priceContext, reviewBlockedBy, reviewNoteSentence }
  from "../src/eventChainText.ts";

const was = { kind: "Synthetic sales report", when: "2025" };
const now = { kind: "Synthetic sales report", when: "2026" };

test("an unchanged event shows its kind and date", () => {
  assert.deepEqual(eventLines({ state: "same", pinned: was, current: was }),
    [{ label: "Event", text: "Synthetic sales report, 2025" }]);
});

test("a changed event shows the pinned and the current record side by side", () => {
  assert.deepEqual(eventLines({ state: "changed", pinned: was, current: now }), [
    { label: "Pinned", text: "Synthetic sales report, 2025" }, { label: "Current", text: "Synthetic sales report, 2026" }]);
});

test("a gone event says so and shows the pinned record", () => {
  const lines = eventLines({ state: "gone", pinned: was, current: null });
  assert.equal(lines[0].text, EVENT_GONE);
  assert.equal(lines[1].text, "Synthetic sales report, 2025");
});

test("a missing or empty part is named as withheld, never empty", () => {
  const lines = eventLines({ state: "changed", pinned: null, current: { kind: "", when: "2026" } });
  assert.match(lines[0].text, /^Withheld/);
  assert.equal(lines[1].text, "kind withheld, 2026");
});

test("a mechanism's mark says what the owner's review of it is, never awaiting a review that was given", () => {
  const at = "2026-11-10T09:00:00+00:00";
  assert.equal(mechanismMark({ state: "awaiting_review", saved_at: null }), "awaiting your review");
  assert.equal(mechanismMark({ state: "approved", saved_at: at }), "approved by the owner on 2026-11-10");
  assert.equal(mechanismMark({ state: "needs_revision", saved_at: at }), "you asked for a revision on 2026-11-10");
  assert.equal(mechanismMark({ state: "approved_earlier_basis", saved_at: at }),
    "approved by the owner on 2026-11-10 on an earlier basis, not on this one");
  // An invalid record history serves no approval state: nothing is claimed either way.
  assert.equal(mechanismMark({ state: null, saved_at: null }), "your review of it cannot be verified");
});

test("a review is refused while a reading is typed", () => {
  assert.equal(reviewBlockedBy("  "), null);
  assert.equal(reviewBlockedBy("half a line"), "Save or clear your reading first.");
});

test("price changes use the spec wording", () => {
  assert.deepEqual(priceChanges(2025, [{ year: 2026, change_pct: "4.0" }]), ["From 2025 to 2026: 4.0%"]);
  assert.deepEqual(priceContext([{ from: 2021, to: 2022, change_pct: "-5.0" }]), ["From 2021 to 2022: -5.0%"]);
});

test("a version answering a review not on this machine says so; any other version says nothing", () => {
  assert.equal(reviewNoteSentence({ answers_review: "f".repeat(64), note: "A later version",
    review_note: "names a review that is not on this machine" }),
  "The version's change names a review that is not on this machine.");
  assert.equal(reviewNoteSentence({ answers_review: "a".repeat(64), note: "A later version", review_note: null }), null);
  assert.equal(reviewNoteSentence({ answers_review: null, note: "A corrected record", review_note: "" }), null);
  assert.equal(reviewNoteSentence(null), null);
  assert.equal(reviewNoteSentence("names a review"), null);
});
