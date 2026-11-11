// An updated brief as readers see it (story view 0.6: the earlier published versions and what the current one
// changed), and the News desk's update-run panel (src/admin/newsUpdate.ts): its arrivals line keeps new, late and
// undated reports apart, its paid line calls an estimate an estimate, its report check refuses what it cannot show, and
// the panel sends nothing on its own.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { readStory } from "../src/contracts/stories.ts";
import { briefUpdated, earlierLine } from "../src/client/storiesView.ts";
import { arrivalsLine, paidLine, reportProblem, updatePaths, UPDATE_VERSION } from "../src/admin/newsUpdate.ts";

const load = () => JSON.parse(readFileSync(new URL("./fixtures/stories-contract-story.json", import.meta.url), "utf8"));
const earlier = { version: 1, published_at: "2026-10-14T09:00:00+00:00", prepared_at: "2026-10-14T08:30:00+00:00",
  method: "editorial", authorship: "editor", recorded_as: null, corrects: null, headline: "Synthetic tariff on steel",
  summary: "The first version.", reports: 2, explained: true };

function updated() {
  const body = load();
  const brief = body.story.brief;
  brief.version = 2;
  brief.revisions = { earlier: [{ ...earlier }], updated_at: "2026-10-14T12:00:00+00:00",
                      changes: ["Adds the report “Synthetic Republic announces 15% tariff” (Synthetic Courier)."] };
  return body;
}

test("a first version has no earlier ones, and an updated one says when and keeps the earlier readable", () => {
  const first = load();
  assert.equal(readStory(first).ok, true);
  assert.deepEqual(first.story.brief.revisions, { earlier: [], changes: [], updated_at: null });
  assert.equal(briefUpdated(first.story.brief, "UTC"), null);
  const body = updated();
  assert.equal(readStory(body).ok, true);
  assert.match(briefUpdated(body.story.brief, "UTC")!, /^Updated .*: version 2 replaces version 1, which stays readable/);
  assert.match(earlierLine(earlier as any, "UTC"), /^Version 1 \(written by an editor\), published .*, from 2 reports, with an economic explanation\.$/);
});

test("revisions that contradict themselves are refused rather than shown", () => {
  const silent = updated();
  silent.story.brief.revisions.changes = [];  // An earlier version, and nothing said about what changed.
  assert.equal(readStory(silent).ok, false);
  const itself = updated();
  itself.story.brief.revisions.earlier[0].version = 2;  // The current version listed as an earlier one.
  assert.equal(readStory(itself).ok, false);
  const corrected = updated();  // An editor's record corrected to an assistant's: shown as corrected, and said so.
  Object.assign(corrected.story.brief.revisions.earlier[0], { method: "assisted", authorship: "ai_assistant",
                                                              recorded_as: "editorial" });
  assert.equal(readStory(corrected).ok, true);
  assert.match(earlierLine(corrected.story.brief.revisions.earlier[0], "UTC"),
               /^Version 1 \(AI-assisted; first recorded as written by an editor\), published/);
  const unchanged = updated();
  unchanged.story.brief.revisions.earlier[0].recorded_as = "editorial";  // "Corrected" to the same method.
  assert.equal(readStory(unchanged).ok, false);
  const relabelled = updated();
  relabelled.story.brief.revisions.earlier[0].authorship = "ai_model";  // An editor's version called AI-drafted.
  assert.equal(readStory(relabelled).ok, false);
  const missing = load();
  delete missing.story.brief.revisions;
  assert.equal(readStory(missing).ok, false);
});

test("the story page shows what changed and the earlier versions", () => {
  const view = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  assert.match(view, /data-brief-updated/);
  assert.match(view, /data-brief-revisions/);
  assert.match(view, /data-earlier-version=\{row\.version\}/);
});

const report = (overrides: Record<string, unknown> = {}) => ({
  update_version: UPDATE_VERSION, stories: [{ kind: "new_development", tone: "todo" }],
  arrivals: [{ class: "published_since" }], completed: [], attention: [], failed: [], next: [],
  counts: { run: { by_class: { published_since: 3, published_before: 1, time_unknown: 0 } } }, ...overrides });

test("arrivals keep newly published, late and undated reports apart", () => {
  assert.equal(arrivalsLine(report() as any), "3 published after the reference time · 1 older report discovered late");
  assert.equal(arrivalsLine(report({ counts: { run: { by_class: { published_since: 0, published_before: 0,
    time_unknown: 2 } } } }) as any), "2 with no stated publication time");
  assert.equal(arrivalsLine(report({ counts: { run: { by_class: { published_since: 0, published_before: 0,
    time_unknown: 0 } } } }) as any), "No report arrived.");
});

test("the paid line calls a total a planning estimate and counts attempts apart", () => {
  const changed = "its story's material changed since the preview";
  const paid = { enabled: false, batches: [], not_attempted: 3, not_attempted_estimate_usd: 0.4125, sendable: 2,
                 sendable_estimate_usd: 0.275, attempted: { recorded: 1 }, statement: "",
                 requests: [{ skipped: null }, { skipped: null }, { skipped: changed }, { skipped: null }] };
  assert.equal(paidLine(paid as any), "3 saved requests not sent: an approval now would send 2 (planning estimate " +
    "$0.2750, not a billing ceiling), skipping 1 (its story's material changed since the preview); 1 attempted: " +
    "1 recorded.");
  const superseded = "it was saved under brief-prompt-6, an earlier request contract than brief-prompt-7, which an " +
    "approval refuses";  // The server's reason: the line repeats it rather than assume a changed story.
  assert.equal(paidLine({ ...paid, sendable: 0, sendable_estimate_usd: 0, requests: [
    { skipped: changed }, { skipped: superseded }, { skipped: superseded }, { skipped: null }] } as any),
    "3 saved requests not sent: an approval now would send 0 (planning estimate $0.0000, not a billing ceiling), " +
    `skipping 3 (${changed}; ${superseded}); 1 attempted: 1 recorded.`);
  assert.equal(paidLine({ ...paid, requests: [] } as any), "No paid request is saved for this run.");
});

test("a report the panel cannot show is refused", () => {
  assert.equal(reportProblem(report()), null);
  assert.match(reportProblem(report({ update_version: "news-update-0.0" }))!, /another version/);
  assert.match(reportProblem(report({ stories: [{ kind: "rumour", tone: "todo" }] }))!, /story/);
  assert.match(reportProblem(report({ arrivals: [{ class: "fresh" }] }))!, /arrival/);
  assert.match(reportProblem(null)!, /not readable/);
});

test("the update panel reads on load and acts only through its buttons", () => {
  assert.equal(updatePaths.step("update-0123456789abcdef", "refresh"),
               "/api/admin/news/updates/update-0123456789abcdef/refresh");
  const panel = readFileSync(new URL("../src/admin/AdminNewsUpdate.tsx", import.meta.url), "utf8");
  const effects = panel.split("useEffect(").slice(1).map((part) => part.split("}, [")[0]);
  assert.equal(effects.length, 2);
  assert.ok(effects.every((part) => part.includes("adminGet") && !part.includes("adminPost")));
  assert.match(panel, /disabled=\{!approve\}/);  // A paid approval needs its own checkbox, then the button.
  assert.match(panel, /estimated_max_usd_total: batch\.estimated_max_usd_total/);
  const desk = readFileSync(new URL("../src/admin/AdminNews.tsx", import.meta.url), "utf8");
  assert.match(desk, /<UpdatePanel version=\{version\} done=\{reload\} \/>/);
});
