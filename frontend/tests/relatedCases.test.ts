// Related Cases client logic, against the views the backend serves (captured by tests/test_related_cases.py into
// fixtures/related-*.json: the committed cases, and matches for SYNTHETIC Inbox entries). Replies are read
// fail-closed: a broken citation, a relabelled review status, a match the rule does not allow, a hint term without a
// saved hint, or a case both related and an overlap is refused. A lost check reply is never sent again.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, test } from "node:test";
import {
  MATCH_VIEW_VERSION, RELATED_HEADER, findRelatedCases, isMatchView, isRelatedCaseView, isRelatedCollection,
  relatedCaseHref, type MatchView, type RelatedCaseView, type RelatedCollection,
} from "../src/relatedCases.ts";

const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; });
const fixture = <T>(name: string): T => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const collection = fixture<RelatedCollection>("related-cases-collection.json");
const bis = fixture<RelatedCaseView>("related-case-bis.json");
const ofac = fixture<RelatedCaseView>("related-case-ofac.json");
const notChecked = fixture<MatchView>("related-match-not-checked.json");
const related = fixture<MatchView>("related-match-related.json");
const overlap = fixture<MatchView>("related-match-overlap.json");
const copy = <T>(value: T): T => structuredClone(value);

test("the served views are read, with both cases and the coverage not built", () => {
  assert.equal(isRelatedCollection(collection), true);
  assert.deepEqual(collection.cases.map((row) => [row.id, row.announced]),
    [["ofac-pdvsa-2019-01-28", "2019-01-28"], ["bis-2022-10-07", "2022-10-07"]]);
  assert.deepEqual(collection.unfinished.map((item) => item.topic),
    ["Tariffs and international trade", "Competition and regulatory policy", "Labor disruptions"]);
  for (const view of [bis, ofac]) {
    assert.equal(isRelatedCaseView(view), true, view.case.id);
    assert.equal(view.case.provenance.human_review, "not_reviewed");
    assert.equal(view.source_check.state, "absent");  // The captured views come from a folder without the copies.
  }
  for (const view of [notChecked, related, overlap]) assert.equal(isMatchView(view), true, view.state);
});

test("the captured matches: one useful match, one topical overlap that is not related", () => {
  assert.equal(notChecked.state, "not_checked");
  assert.equal(notChecked.match, null);
  const [row] = related.match!.related;
  assert.equal(row.case_id, "bis-2022-10-07");
  assert.deepEqual(row.shared.map((item) => item.dimension), ["instrument", "sector"]);
  assert.deepEqual(row.unknown.map((item) => item.dimension), ["geography", "agency"]);
  assert.equal(row.differs.length, 0);
  assert.equal(overlap.match!.related.length, 0);
  assert.deepEqual(overlap.match!.overlaps.map((item) => [item.case_id, item.missing]),
    [["ofac-pdvsa-2019-01-28", "instrument"]]);
});

test("the case list is refused when IDs repeat, dates are not calendar dates or the order is wrong", () => {
  const twice = copy(collection);
  twice.cases[1].id = twice.cases[0].id;
  const badDay = copy(collection);
  badDay.cases[0].announced = "2019-02-30";
  const reversed = copy(collection);
  reversed.cases.reverse();
  for (const view of [twice, badDay, reversed]) assert.equal(isRelatedCollection(view), false);
});

test("a case view is refused when a citation, the review status, the dates or the position do not hold", () => {
  const broken: ((view: RelatedCaseView) => void)[] = [
    (view) => { view.case.scope[0].facts = ["not-a-fact"]; },
    (view) => { (view.case.provenance as { human_review: string }).human_review = "reviewed"; },
    (view) => { (view.case.provenance as { currency: string }).currency = "current"; },
    (view) => { view.case.dates.push({ ...view.case.dates[0] }); },
    (view) => { view.case.dates[1].date = null; view.case.dates[1].note = null; },
    (view) => { view.case.facts[0].quotes = []; },
    (view) => { view.source_check.sha256 = "0".repeat(64); },
    (view) => { view.next = { id: "x", title: "x" }; },
    (view) => { (view as { provider_called: boolean }).provider_called = true; },
  ];
  for (const [index, change] of broken.entries()) {
    const view = copy(bis);
    change(view);
    assert.equal(isRelatedCaseView(view), false, `change ${index}`);
  }
});

test("a match is refused when it shows what the rule does not allow", () => {
  const broken: ((view: MatchView) => void)[] = [
    (view) => { view.match!.related[0].shared = view.match!.related[0].shared.filter((s) => s.dimension !== "instrument"); },
    (view) => { view.match!.related[0].shared = view.match!.related[0].shared.filter((s) => s.dimension !== "sector"); },
    (view) => { view.match!.related[0].shared_dimensions = 3; },
    (view) => { view.match!.related[0].shared[0].found[0].hint = true; },  // A hint term, but no saved hint.
    (view) => { view.match!.related[0].rests_on_hint = true; },  // No note.
    (view) => { view.match!.overlaps.push({ ...overlap.match!.overlaps[0], case_id: "bis-2022-10-07" }); },
    (view) => { view.match = null; },
    (view) => { (view as { written: boolean }).written = true; },
    (view) => { view.event.identity.id = "another"; },
  ];
  for (const [index, change] of broken.entries()) {
    const view = copy(related);
    change(view);
    assert.equal(isMatchView(view), false, `change ${index}`);
  }
  const wrongMissing = copy(overlap);
  wrongMissing.match!.overlaps[0].missing = "sector_or_country";
  assert.equal(isMatchView(wrongMissing), false);
  const notCheckedWithMatch = copy(notChecked);
  notCheckedWithMatch.match = related.match;
  assert.equal(isMatchView(notCheckedWithMatch), false);
});

test("the check sends its header and body once; a lost reply is unconfirmed and never sent again", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ view_version: MATCH_VIEW_VERSION, match_id: "a".repeat(64), created: true,
      related: 1, overlaps: 0, provider_called: false }), { status: 201 });
  }) as typeof fetch;
  const done = await findRelatedCases("inbox", "wto-news:32de5add4d0365be3615");
  assert.equal(done.state, "done");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/related-cases/events/inbox/wto-news%3A32de5add4d0365be3615/matches");
  assert.equal((calls[0].init.headers as Record<string, string>)[RELATED_HEADER], "1");
  assert.equal(calls[0].init.body, JSON.stringify({ find_related_cases: true }));

  calls.length = 0;
  globalThis.fetch = (async () => { calls.push({ url: "", init: {} }); throw new TypeError("network"); }) as typeof fetch;
  const lost = await findRelatedCases("capture", "x");
  assert.equal(lost.state, "unconfirmed");
  assert.equal(calls.length, 1);

  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "Refused" }), { status: 422 })) as typeof fetch;
  assert.deepEqual(await findRelatedCases("inbox", "x"), { state: "refused", message: "Refused" });
  globalThis.fetch = (async () => new Response(JSON.stringify({ view_version: MATCH_VIEW_VERSION, match_id: "x",
    created: true, provider_called: false }), { status: 201 })) as typeof fetch;
  assert.equal((await findRelatedCases("inbox", "x")).state, "unconfirmed");
});

test("case addresses are encoded", () => {
  assert.equal(relatedCaseHref("bis-2022-10-07"), "/library/historical/bis-2022-10-07");
  assert.equal(relatedCaseHref("a/b"), "/library/historical/a%2Fb");
});
