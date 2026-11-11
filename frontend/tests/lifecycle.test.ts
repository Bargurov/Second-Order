// The interface freeze's client logic: nothing preselected in the form, strict payloads, and replies read fail-closed.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  LIFECYCLE_VERSION, emptyManual, hypothesisHref, isDrafts, isPreview, manualPayload, readable, type ManualForm,
} from "../src/lifecycle.ts";
import { matchRoute } from "../src/routes.ts";

const ID = "c3afef5162762c91c50ece49cf0dc62ba63321a60dc6074afa5b86d8e7f6f4e4";

function complete(): ManualForm {
  const form = emptyManual();
  return {
    ...form, headline: "Synthetic release", source_url: "https://example.com/r", published_at: "2026-09-15T14:00:00-04:00",
    story_id: "synthetic", summary: "A synthetic summary.", authoring: "Written by me without AI assistance",
    primary: "yield:ust2y_cmt_h15",
    legs: form.legs.map((leg) => ({ ...leg, expected: "down", horizon: "5", link: "proxy", channel: "Policy path",
                                    rationale: "Because.", falsifier: "A large rise.", headline_reports_move: "no" })),
  };
}

test("the manual form preselects nothing: every direction, horizon, link, flag and the primary leg is chosen", () => {
  const form = emptyManual();
  assert.equal(form.primary, "");
  for (const leg of form.legs) {
    assert.deepEqual([leg.expected, leg.horizon, leg.link, leg.headline_reports_move], ["", "", "", ""]);
  }
  const { payload, missing } = manualPayload(form);
  assert.equal(payload, null);
  assert.ok(missing.includes("the primary leg"));
  assert.ok(missing.some((item) => item.endsWith("whether the headline reports the move")));
});

test("a complete form becomes the server's strict input, with exactly one primary leg", () => {
  const { payload, missing } = manualPayload(complete());
  assert.deepEqual(missing, []);
  assert.ok(payload);
  assert.deepEqual(payload.legs.map((leg) => [leg.observable_id, leg.primary, leg.horizon, leg.headline_reports_move]),
                   [["yield:ust2y_cmt_h15", true, 5, false], ["yield:ust10y_cmt_h15", false, 5, false]]);
  const dateOnly = manualPayload({ ...complete(), published_at: "2026-09-15" });
  assert.equal(dateOnly.payload, null);  // A date-only time is never padded into a time here.
  assert.ok(dateOnly.missing.includes("publication time with its UTC offset"));
});

test("replies are read only at this client's version, and a preview must bind what it shows", () => {
  const preview = {
    lifecycle_version: LIFECYCLE_VERSION, preview_sha256: "a".repeat(64), freezable: true, blockers: [],
    provider_called: false, written: false, baseline: { snapshot_id: "b".repeat(64) },
    binding: { effective_hypothesis: {}, baseline_snapshot_id: "b".repeat(64) },
  };
  assert.equal(readable(preview, isPreview), true);
  assert.equal(readable({ ...preview, lifecycle_version: "lifecycle-freeze-0.0" }, isPreview), false);
  assert.equal(readable({ ...preview, blockers: ["Stale baseline"] }, isPreview), false);  // freezable must agree.
  assert.equal(readable({ ...preview, provider_called: true }, isPreview), false);
  assert.equal(readable({ ...preview, binding: { ...preview.binding, baseline_snapshot_id: "c".repeat(64) } }, isPreview),
               false);
  const drafts = { lifecycle_version: LIFECYCLE_VERSION, drafts: [{ draft_id: ID, eligible: true, reasons: [] }] };
  assert.equal(readable(drafts, isDrafts), true);
  assert.equal(readable({ ...drafts, drafts: [{ draft_id: ID, eligible: true, reasons: ["Mock"] }] }, isDrafts), false);
});

test("hypotheses have a list address and one read-only address per frozen record", () => {
  assert.deepEqual(matchRoute("/hypotheses"), { page: "hypotheses" });
  assert.deepEqual(matchRoute("/hypotheses/"), { page: "hypotheses" });
  assert.deepEqual(matchRoute(hypothesisHref(ID)), { page: "hypothesis", id: ID });
  assert.deepEqual(matchRoute("/hypotheses/%E0%A4"), { page: "not-found", reason: "malformed" });
  for (const path of ["/hypotheses/a/b", "/Hypotheses", "/hypothesis"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
});
