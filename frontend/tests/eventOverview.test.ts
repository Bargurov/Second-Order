// The private event overview: its addresses, the way back from the review screen, and the words each section uses
// for what it has and does not have. SYNTHETIC values shaped like the server's replies.
import assert from "node:assert/strict";
import test from "node:test";
import { returnLabel, returnPath } from "../src/analyses.ts";
import {
  analysisGap, marketSummary, originLine, overviewHref, reviewFromOverview, triageGap, triageProvenance,
  type MarketSection, type OriginLink, type TriageMode, type TriageSection,
} from "../src/eventOverview.ts";
import { matchRoute } from "../src/routes.ts";

const CAPTURE = "20261005T080159226239Z-fcf7bcfead4c";
const ITEM = "fed-monetary:0123456789abcdef0123";

test("an overview has one address per Inbox entry or capture, apart from the research Dossier", () => {
  assert.equal(overviewHref("inbox", ITEM), "/events/inbox/fed-monetary%3A0123456789abcdef0123");
  assert.deepEqual(matchRoute(overviewHref("inbox", ITEM)), { page: "event-overview", kind: "inbox", id: ITEM });
  assert.deepEqual(matchRoute(`/events/capture/${CAPTURE}/`), { page: "event-overview", kind: "capture", id: CAPTURE });
  assert.deepEqual(matchRoute("/events/capture/%E0%A4"), { page: "not-found", reason: "malformed" });
  for (const path of ["/events", "/events/other/x", "/events/capture", "/events/capture/a/b"]) {
    assert.deepEqual(matchRoute(path), { page: "not-found", reason: "unknown" }, path);
  }
  assert.deepEqual(matchRoute(`/h/${"a".repeat(64)}`), { page: "dossier", id: "a".repeat(64) });
});

test("the review screen returns to the overview it was opened from, and nowhere else", () => {
  const href = reviewFromOverview("d".repeat(64), "capture", CAPTURE);
  assert.equal(href, `/?draft=${"d".repeat(64)}&from=%2Fevents%2Fcapture%2F${CAPTURE}`);
  const back = returnPath(href.slice(1));
  assert.equal(back, `/events/capture/${CAPTURE}`);
  assert.equal(returnLabel(back!), "← Back to the event overview");
  assert.equal(returnLabel("/analyses"), "← Back to My analyses");
  assert.equal(returnPath(`?from=${encodeURIComponent(overviewHref("inbox", ITEM))}`), "/events/inbox/fed-monetary%3A0123456789abcdef0123");
  for (const hostile of ["/events/capture/x?y=1", "/events/capture/x#top", "/events/other/x", "//evil.example/events/capture/x",
                         "/events/capture/x/y", "https://evil.example/events/capture/x"]) {
    assert.equal(returnPath(`?from=${encodeURIComponent(hostile)}`), null, hostile);
  }
});

const section = (state: TriageSection["state"]): TriageSection =>
  ({ state, fingerprint: null, modes: [], relations: [], unreadable_requests: [] });

test("an empty triage section says why, and never matches by title or date", () => {
  assert.equal(triageGap(section("results")), null);
  assert.match(triageGap(section("none"))!, /exact entry version/);
  assert.match(triageGap(section("no_origin"))!, /nothing is matched by title or date/);
  assert.match(triageGap(section("origin_unreadable"))!, /cannot be read/);
});

test("triage provenance names the response, its configuration and a local re-check as such", () => {
  const mode: TriageMode = {
    mode: "paid", mode_note: "", status: "earlier_version", claim: null, other_versions_with_results: 0,
    result: { category: "Policy decision", event_type: "FOMC statement", summary: "s" },
    provenance: { triage_id: "triage-130bbb", mode: "paid", current_config: false, received_at: "2026-10-09T11:00:00+00:00",
                  config: { model: "claude-haiku-5-5", prompt_version: "triage-prompt-3", schema_version: "triage-schema-3" },
                  request_sha256: "x", response_id: "msg", request_id: "req", validation_policy: "triage-validation-3",
                  revalidation: { validation_policy: "triage-validation-3", revalidated_at: "2026-10-09T12:00:00+00:00",
                                  original_outcome: "not_accepted", original_validation_policy: "triage-validation-1",
                                  original_message: "m" } },
  };
  const line = triageProvenance(mode);
  assert.match(line, /^Model response from triage-130bbb, received 2026-10-09T11:00:00\+00:00; claude-haiku-5-5, triage-prompt-3/);
  assert.match(line, /\(an earlier configuration\)/);
  assert.match(line, /Accepted on a local re-check under triage-validation-3 .* recorded as not accepted under triage-validation-1\. Nothing was regenerated or re-sent\./);
});

test("an origin line states what was recorded, or that nothing was", () => {
  assert.match(originLine({ state: "none", problem: null, link: null, entry: null }), /Nothing is inferred from its title/);
  const verified: OriginLink = {
    state: "verified", problem: null, entry: { held: true, location: "current", current_content_sha256: "b",
                                               same_version_as_current: false, title_now: "t" },
    link: { capture_id: CAPTURE, recorded_at: "2026-10-09T15:00:00+00:00", statement: "",
            inbox: { item_id: ITEM, content_sha256: "a", version: 1, versions: 2, location: "current", title: "t",
                     link: "l", feed_timestamp_raw: null },
            form: { headline_matches: false, source_url_matches: true } },
  };
  assert.equal(originLine(verified), "Started from Inbox entry version 1 of 2 (an earlier version; the entry has changed " +
    "since), recorded 2026-10-09T15:00:00+00:00; before capture, the headline was edited.");
});

test("the market section states every gap and never claims more than it holds", () => {
  const base: MarketSection = { state: "unsupported", href: null, problem: null, view: null, plan: null,
    event: { key: "k", supported: false, family_label: null, outside: "Energy … outside this first slice.", context: null,
             suggestion: null, suggestion_problem: null, problem: null, confirmation_stale: null } };
  assert.equal(marketSummary(base), "Energy … outside this first slice.");
  assert.match(marketSummary({ ...base, state: "stale_confirmation",
    event: { ...base.event!, confirmation_stale: { version: 1, context_date: "2026-09-16", title: "Old title" } } }),
    /confirmed for an earlier version of this entry \(“Old title”\)\. It does not carry over/);
  assert.match(marketSummary({ ...base, state: "partial", plan: { needed_sessions: 20, held_sessions: 12,
    missing_sessions: 8, future_sessions: 0, requests: 1 } }), /12 of 20 sessions before today\. Missing, future and conflicting/);
  assert.match(marketSummary({ ...base, state: "no_data" }), /nothing is requested by opening it/);
});

test("analysis gaps point to the existing workflow and say nothing is sent", () => {
  assert.match(analysisGap("none", null), /nothing is sent without your approval/);
  assert.equal(analysisGap("incomplete", "An attempt was reserved."),
               "An attempt was started but did not finish; it is kept as recorded and is never sent again. An attempt was reserved.");
});
