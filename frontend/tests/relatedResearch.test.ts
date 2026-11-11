// Related research client logic, against views the backend serves for SYNTHETIC events (captured by
// tests/test_related_research.py into fixtures/related-research-*.json). Replies are read fail-closed: an exact-event
// link needs the event's own address and date, family and topic links need an earlier case and a dated event, each
// target appears once in strength order, and a historical case shown above is never repeated.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { familyMoreHref, isResearchView, RESEARCH_VIEW_VERSION, type ResearchView } from "../src/relatedResearch.ts";

const fixture = (name: string): ResearchView =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const same = fixture("related-research-same-event.json");
const family = fixture("related-research-family.json");
const topic = fixture("related-research-topic.json");
const none = fixture("related-research-none.json");
const copy = (view: ResearchView): ResearchView => structuredClone(view);

test("the served views are read, one per relationship, and an empty result is valid", () => {
  for (const view of [same, family, topic, none]) assert.equal(isResearchView(view), true, view.event.title);
  assert.equal(same.view_version, RESEARCH_VIEW_VERSION);
  assert.deepEqual(same.links.map((link) => [link.relation, link.target.id]), [["same_event", "eia-tie-2026-09-30"]]);
  assert.deepEqual(family.links.map((link) => [link.relation, link.target.id]), [["release_family", "fomc-2025-06-18"]]);
  assert.deepEqual(topic.links.map((link) => [link.relation, link.target.id]), [["topic", "eia-tie-2026-09-25"]]);
  assert.deepEqual(none.links, []);
  assert.match(none.notes.join(" "), /later case is not suggested/);
});

test("every link says what kind of content it is and when it was written", () => {
  for (const link of [same, family, topic].flatMap((view) => view.links)) {
    assert.deepEqual(link.status.labels, ["Editorial case", "AI-assisted", "Not human-reviewed", "Not research evidence"]);
    assert.match(link.status.timing, /^Written on /);
  }
  assert.equal(family.links[0].family!.case_document, "statement");
  assert.equal(family.links[0].family!.event_document, "minutes");
  assert.equal(familyMoreHref(family.links[0]), "/library?category=monetary-policy");
});

test("a reply that breaks the selection's rules is refused", () => {
  const broken: [ResearchView, (view: ResearchView) => void][] = [
    [same, (view) => { view.links[0].address = "https://www.eia.gov/todayinenergy/detail.php?id=1"; }],
    [same, (view) => { view.event.date = "2026-10-01"; }],  // An exact-event link needs the same date.
    [family, (view) => { view.links[0].target.date = "2026-10-08"; }],  // A later case.
    [family, (view) => { view.event.date = null; }],  // An undated event gets no family link.
    [topic, (view) => { view.links[0].topic!.found = []; }],
    [topic, (view) => { view.links.push(copy(topic).links[0]); }],  // A repeated target.
    [topic, (view) => { view.links.unshift({ ...copy(family).links[0] }); view.links.reverse(); }],  // Order.
    [family, (view) => { view.links[0].target.href = "/library/another-case"; }],
    [family, (view) => { view.links[0].status.source_check = "verified"; }],  // Only historical cases are checked.
    [same, (view) => { (view as { written: boolean }).written = true; }],
    [same, (view) => { (view as { hints_used: boolean }).hints_used = true; }],
  ];
  for (const [index, [base, change]] of broken.entries()) {
    const view = copy(base);
    change(view);
    assert.equal(isResearchView(view), false, `change ${index}`);
  }
});

test("a historical case shown in the section above is never repeated here", () => {
  const view = copy(same);
  view.links[0] = { ...view.links[0], target: { ...view.links[0].target, collection: "historical", id: "bis-2022-10-07",
    href: "/library/historical/bis-2022-10-07" }, status: { ...view.links[0].status, kind: "historical",
    source_check: "absent" } };
  assert.equal(isResearchView(view), true);
  view.shown_in_historical = ["bis-2022-10-07"];
  assert.equal(isResearchView(view), false);
});
