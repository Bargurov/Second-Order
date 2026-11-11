// How the Client says what a story states (src/client/storiesView.ts) over the SYNTHETIC stories fixtures: the
// interests' labels equal the server's vocabulary, times say when they are only "first seen", coverage says what was
// counted once and why, a brief's provenance says what it rests on, and nothing the Client says carries the
// administrator's vocabulary. The News pages link headlines to the internal story page.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { BRIEF_STATE_TEXT, INTEREST_LABEL, USE_TEXT, authorshipTag, briefPreview, briefSources, coverageText,
  deeperStages, inHotNow,
  materialBasis, provenance, publishedText, storyTimes, textLine, timeLine,
} from "../src/client/storiesView.ts";
import { INTERESTS } from "../src/contracts/news.ts";

const fixtures = new URL("./fixtures/", import.meta.url);
const load = <T = Record<string, any>>(name: string): T =>
  JSON.parse(readFileSync(new URL(`${name}.json`, fixtures), "utf8"));
const ADMIN_ONLY = /claude|sonnet|opus|haiku|anthropic|openai|\busd\b|dollar|\btokens?\b|\bcosts?\b|\bproviders?\b|\bmodels?\b|\bprices?\b/i;

test("the interests' labels are the server's vocabulary, every one of them", () => {
  const vocabulary = load("news-contract-interests").interests.vocabulary;
  assert.deepEqual(Object.keys(INTEREST_LABEL), [...INTERESTS]);
  for (const row of vocabulary) assert.equal(INTEREST_LABEL[row.interest as keyof typeof INTEREST_LABEL], row.label);
  assert.equal(vocabulary.length, INTERESTS.length);
});

test("times say when they are only when this server first saw a report", () => {
  const notime = load("stories-contract-story-notime").story;
  assert.match(storyTimes(notime, "UTC")[0], /first seen by this server; the feed states no time/);
  const story = load("stories-contract-story").story;
  assert.match(storyTimes(story, "UTC")[0], /^First reported \d+ \w+ 2026, \d\d:\d\d \(UTC\)$/);
  const source = notime.sources[0];
  assert.match(publishedText(source, "UTC"), /^No publication time stated; first seen/);
});

test("a feed that states only a date is shown as that date, never as a time of day", () => {
  assert.equal(timeLine("2026-10-21T23:59:59+00:00", "dated", "Asia/Jerusalem", "First reported"),
    "First reported 21 Oct 2026: the feed states the date, not the time");
  const source = load("stories-contract-story-notime").story.sources[0];
  const contradicts = { ...source, published: { ...source.published, state: "unstated",
    as_stated: "Thu, 22 Oct 2026  09:00:00 EST", utc: null, date: null } };
  assert.match(publishedText(contradicts, "UTC"),
    /^The feed's time \(“Thu, 22 Oct 2026 09:00:00 EST”\) is not a usable instant; first seen \d+ \w+ 2026/);
});

test("coverage counts publishers apart from reporting origins, by kind, and confirmed origins apart from possible ones", () => {
  const story = load("stories-contract-story").story;
  assert.equal(coverageText(story.coverage),
               "2 reports from 2 publishers: 1 reporting origin (1 newsroom); 1 copy counted with its origin.");
  assert.match(coverageText({ ...story.coverage, company_statements: 1 }), /company's own words, not independent/);
  const counts = { reports: 4, publishers: 4, origins: 3, news_origins: 2, official_origins: 1, company_origins: 0,
                   reporting_origins: 3, confirmed_news: 1, confirmed_official: 1, possible_news: 1, possible_official: 0,
                   uncertain: 1, repeats: 1, company_statements: 0, official_releases: 1 };
  assert.equal(coverageText(counts), "4 reports from 4 publishers: 2 confirmed reporting origins (1 newsroom, 1 " +
               "official statement) and 1 possible origin (1 newsroom) whose independence is not established; 1 copy " +
               "counted with its origin.");
  assert.equal(coverageText({ ...counts, confirmed_news: 2, possible_news: 0, uncertain: 0 }),
               "4 reports from 4 publishers: 3 confirmed reporting origins (2 newsrooms, 1 official statement); 1 " +
               "copy counted with its origin.");
  const unverified = coverageText({ ...counts, reports: 3, publishers: 3, origins: 3, news_origins: 2,
                                    official_origins: 1, confirmed_news: 0, confirmed_official: 1, possible_news: 2,
                                    uncertain: 2, repeats: 0 });
  assert.equal(unverified, "3 reports from 3 publishers: 1 confirmed reporting origin (1 official statement) and 2 " +
               "possible origins (2 newsrooms) whose independence is not established.");
  for (const text of [unverified, coverageText(counts)]) assert.doesNotMatch(text, /independent origin/);
  assert.equal(coverageText({ ...counts, reports: 2, publishers: 1, origins: 1, news_origins: 0, official_origins: 0,
                              company_origins: 1, reporting_origins: 0, confirmed_news: 0, confirmed_official: 0,
                              possible_news: 0, uncertain: 0, company_statements: 2, official_releases: 0 }),
               "2 reports from 1 publisher: company statements (a company's own words), not independent reporting; " +
               "1 copy counted with its origin.");
});

test("a brief's provenance names its method, version and material, and newer reports", () => {
  const brief = load("stories-contract-story").story.brief;
  const lines = provenance(brief, "UTC");
  assert.match(lines[0], /^Written by an editor from the material below\. Version 1, prepared/);
  const assisted = { ...brief, method: "assisted", authorship: "ai_assistant", method_label:
    "Written with an AI assistant from the material below.", review: { state: "not_reviewed", statement:
    "No editor has read this version: it was published as prepared." } };
  assert.match(provenance(assisted, "UTC")[0],
    /^Written with an AI assistant from the material below\. No editor has read this version: it was published as prepared\. Version 1/);
  assert.match(lines[1], /The full publications were not read/);
  assert.equal(lines.length, 2);
  assert.match(provenance({ ...brief, reports_since: 2 }, "UTC")[2], /^2 reports have arrived since this brief/);
});

test("a story page says whether it is in Hot now from the server's own signals (news-rank-0.4)", () => {
  const story = load("stories-contract-story").story;
  assert.equal(inHotNow(story), !story.older);
  const said = (signal: string, text: string) => ({ signal, text });
  const fresh = { older: false, signals: [said("freshness", "Latest report 2 hours ago.")] };
  assert.equal(inHotNow(fresh), true);
  assert.equal(inHotNow({ ...fresh, signals: [...fresh.signals, said("relevance", "x")] }), false);
  assert.equal(inHotNow({ ...fresh, signals: [...fresh.signals, said("statements_only", "x")] }), false);
  assert.equal(inHotNow({ ...fresh, older: true }), false);
  assert.equal(inHotNow({ older: true, signals: [...fresh.signals, said("priority", "Marked as major.")] }), true);
  const page = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  assert.match(page, /How this story is ordered/);
  assert.match(page, /Why it is in the economic news/);
  assert.match(page, /Other developments, newest first/);
});

test("nothing the Client says about stories carries the administrator's vocabulary", () => {
  for (const text of [...Object.values(BRIEF_STATE_TEXT), ...Object.values(USE_TEXT), ...Object.values(INTEREST_LABEL)]) {
    assert.doesNotMatch(text, ADMIN_ONLY, text);
  }
});

test("headlines open the internal story page; publisher links are labelled sources", () => {
  const home = readFileSync(new URL("../src/client/components/NewsHome.tsx", import.meta.url), "utf8");
  assert.match(home, /<Link to=\{href\.story\(story\.story_id\)\}>\{story\.title\}<\/Link>/);
  assert.doesNotMatch(home, /target="_blank"[^>]*>\{story\.title\}/);
  const card = readFileSync(new URL("../src/client/components/NewsEntryCard.tsx", import.meta.url), "utf8");
  assert.match(card, /<Link to=\{href\.story\(entry\.story_id\)\}>\{entry\.title\}<\/Link>/);
  assert.match(card, /Publisher's page \(opens a new tab\)/);
  const page = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  assert.match(page, /<h2 id="sources-title">Sources<\/h2>/);
  assert.match(page, /<a href=\{source\.link\} target="_blank" rel="noreferrer">\{source\.title\}<\/a>/);
  const app = readFileSync(new URL("../src/client/ClientApp.tsx", import.meta.url), "utf8");
  assert.match(app, /<Link to=\{href\.news\} className="wordmark">/);
});

test("a brief's label says who prepared it and whether an editor read it, from its own record", () => {
  const brief = load("stories-contract-story").story.brief;
  assert.equal(authorshipTag(brief), "Written by an editor");
  assert.equal(authorshipTag({ authorship: "ai_assistant", review: { state: "not_reviewed", statement: "" } }),
               "AI-assisted · not read by an editor");
  assert.equal(authorshipTag({ authorship: "ai_model", review: { state: "read_by_editor", statement: "" } }),
               "AI-drafted · read by an editor");
  const story = load("stories-contract-story").story;
  const number = (entry: string) => story.sources.findIndex((row: any) => row.entry_id === entry) + 1;
  assert.match(briefSources(brief, number), /^Synthetic \w+ \[\d\](; Synthetic \w+ \[\d\])*$/);
  for (const text of Object.values(BRIEF_STATE_TEXT)) assert.doesNotMatch(text, /editors? (wrote|prepared)/i);
  assert.equal(BRIEF_STATE_TEXT.insufficient, "Not enough material for a brief");
});

test("a source says whether its publication's text is held, in part, unreadable or not yet retrieved", () => {
  const source = load("stories-contract-story-text").story.sources[0];
  assert.match(textLine(source.text, "UTC") ?? "", /^Full text retained from the publisher's page \([\d,]+ characters, retrieved /);
  const none = { state: "not_supported", characters: null, retrieved_at: null, partial_reason: null, detail: "x" } as const;
  assert.equal(textLine(none, "UTC"), null);
  assert.match(textLine({ ...none, state: "failed", detail: "The page does not have the layout" }, "UTC") ?? "",
               /could not be read: The page does not have the layout\. Its headline and excerpt are used\.$/);
  assert.match(textLine({ ...none, state: "not_retrieved" }, "UTC") ?? "", /has not been retrieved/);
  const row = load("stories-contract-deeper-text").deeper.material.reports[0];
  assert.match(materialBasis(row), /^Full text, [\d,]+ characters$/);
  assert.equal(materialBasis({ excerpt: "x" }), "Headline and the feed's excerpt");
  assert.equal(materialBasis({ excerpt: null }), "Headline only");
});

test("a card previews a brief in whole sentences, never rewriting it", () => {
  assert.equal(briefPreview("Short summary."), "Short summary.");
  const long = "First sentence of the brief states the measure. Second sentence adds the date it applies. " +
    "A third sentence is long enough that keeping it would go past the preview's limit of characters by a margin.";
  assert.equal(briefPreview(long, 100), "First sentence of the brief states the measure. Second sentence adds the date it applies.");
  const oneLong = `${"A first sentence that runs on ".repeat(10).trim()}.`;
  assert.equal(briefPreview(`${oneLong} Then more.`, 260), oneLong);  // A long first sentence stays whole.
  const unbroken = "word ".repeat(80).trim();
  const cut = briefPreview(unbroken, 50);
  assert.ok(cut.endsWith("…") && cut.length <= 51 && unbroken.startsWith(cut.slice(0, -1)));
  const home = readFileSync(new URL("../src/client/components/NewsHome.tsx", import.meta.url), "utf8");
  assert.match(home, /briefTag\(story\.brief\)/);
  assert.match(home, /is-compact/);
});

test("a preview preserves the opening when abbreviations and decimals occur", () => {
  for (const first of [
    "The U.S. Trade Representative will review a 3.5% duty.",
    "U.S. output expanded 3.5% in September.",
  ]) {
    const summary = `${first} ${"A later sentence adds background. ".repeat(12)}`;
    const preview = briefPreview(summary, first.length + 4);
    assert.equal(preview, first);
    assert.ok(summary.startsWith(preview));
  }
});

test("Go deeper says which stage the server is ready for, from the account's own reasons", () => {
  const efforts = [{ effort: "low" as const, label: "Low" }];
  const missing = (...reasons: string[]) => ({ efforts: reasons.includes("no_credit_policy") ? [] : efforts,
    analysis: { available: false as const, reason: reasons[0] as any, detail: "x",
                reasons: reasons.map((reason) => ({ reason: reason as any, detail: "x" })) } });
  const none = deeperStages(missing("sending_disabled", "no_credit_policy"));
  assert.deepEqual(none.map((row) => row.ready), [false, false, false]);
  assert.match(none[0].text, /No credit terms are published.*Nothing has been chosen for you/);
  assert.match(none[2].text, /switched off on this server/);
  const ready = deeperStages({ efforts, analysis: { available: true, reason: null, detail: null, reasons: [] } });
  assert.deepEqual(ready.map((row) => row.ready), [true, true, true]);
  const noSend = deeperStages(missing("sending_disabled"));
  assert.deepEqual(noSend.map((row) => row.ready), [true, true, false]);
});
