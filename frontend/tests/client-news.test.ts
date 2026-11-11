// What the Client says and sends for current news (src/client/newsView.ts and the news refusals in refusals.ts),
// against the SYNTHETIC news-contract fixtures: publication times stay the feed's (never a retrieval time, and unknown
// when the feed's is unusable), every feed's state is said as the server reports it, filtering what is shown sends
// nothing, a search is checked before it is sent and keeps its key only to repeat an unconfirmed one, the paste step
// never treats an excerpt as the publication, and limits are the server's figures. Also the account binding's 401
// account_changed, recognised from the reply itself. Page rules only; the server's own checks are not proved here.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { readLimits, readNews, type Limits, type NewsEntry, type NewsSource, type NewsView } from "../src/contracts/news.ts";
import type { ApiError } from "../src/contracts/user.ts";
import { changedAccount } from "../src/client/identity.ts";
import {
  NO_FILTER, clearPaste, coverageText, filtered, offerPaste, pasteOffer, peekPaste, publishedText, queryWords, quotaText,
  resetText, retrievedText, sameSelection, searchKey, searchProblem, sourceStateText, storageText, type SearchBody,
} from "../src/client/newsView.ts";
import { noticeFor, sessionEndedBy } from "../src/client/refusals.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const read = <T>(reader: (body: unknown) => { ok: boolean; value?: T; problem?: string }, name: string): T => {
  const result = reader(load(name));
  assert.ok(result.ok, `${name}: ${result.problem}`);
  return result.value as T;
};
const news = read<{ news: NewsView }>(readNews, "news-contract-news").news;
const all = read<{ news: NewsView }>(readNews, "news-contract-news-all").news;
const empty = read<{ news: NewsView }>(readNews, "news-contract-news-empty").news;
const limits = read<{ limits: Limits }>(readLimits, "news-contract-limits").limits;
const unset = read<{ limits: Limits }>(readLimits, "news-contract-limits-no-policy").limits;
const errors = load<Record<string, ApiError>>("user-contract-errors");
const ZONE = "Asia/Jerusalem";
const entryOf = (state: string) => all.entries.find((entry) => entry.published.state === state)!;
const sourceOf = (key: string) => news.sources.find((source) => source.source === key)!;
const refused = (code: string, status = 409) => noticeFor({ state: "refused", status, error: errors[code] }, null, ZONE);
const ADMIN_ONLY = /claude|sonnet|opus|haiku|anthropic|openai|\$\s?\d|\busd\b|dollar|\btokens?\b|\bcosts?\b|\bproviders?\b|\bmodels?\b|\busage\b/i;
const said: string[] = [];
const say = <T>(value: T): T => {
  said.push(JSON.stringify(value));
  return value;
};

test("a stated publication time is the feed's own, in the quota zone, with the feed's words beside it", () => {
  const stated = entryOf("stated");
  const shown = say(publishedText(stated.published, ZONE));
  assert.equal(stated.published.utc, "2026-10-07T13:00:00+00:00");  // The fixture's "Wed, 07 Oct 2026 09:00:00 EDT".
  assert.equal(shown.line, "Published 7 Oct 2026, 16:00 (Asia/Jerusalem)");
  assert.equal(shown.note, `The feed states “${stated.published.as_stated}”.`);
  assert.doesNotMatch(shown.line, /Retrieved/);
});

test("a date-only or unusable feed time stays unknown: no time of day is invented, and no retrieval time stands in", () => {
  const dated = say(publishedText(entryOf("date_only").published, ZONE));
  assert.equal(dated.line, "Published 8 Oct 2026; the feed states no time of day");
  assert.match(dated.note!, /placeholder time/);
  const unstated = entryOf("unstated");
  const unknown = say(publishedText(unstated.published, ZONE));
  assert.equal(unknown.line, "Publication time unknown: the feed's timestamp cannot be used");
  assert.match(unknown.note!, /contradicts the date/);
  assert.match(say(retrievedText(unstated, ZONE)), /^Retrieved|^First retrieved/);
  const retained: NewsEntry = { ...unstated, listing: "retained" };
  assert.match(say(retrievedText(retained, ZONE)), /^No longer in the feed; last retrieved/);
});

test("every feed's state is said as the server reports it: retrieved, stale, not requested, failed, never, unreadable", () => {
  const ok = say(sourceStateText(sourceOf("fed-monetary"), ZONE));
  assert.equal(ok.tone, "ok");
  assert.match(ok.text, /^Retrieved 14 Oct 2026, 12:00 \(Asia\/Jerusalem\) · 2 entries held$/);
  const notRequested = say(sourceStateText(sourceOf("bls-empsit"), ZONE));
  assert.deepEqual([notRequested.tone, notRequested.text], ["missing", sourceOf("bls-empsit").last_attempt!.detail]);
  const base = sourceOf("eia-todayinenergy");
  const failedAfter: NewsSource = { ...base, state: "failed", stale: true,
    last_attempt: { at: "2026-10-14T10:00:00+00:00", outcome: "failed", detail: "HTTP 503 from the publisher." } };
  const stale = say(sourceStateText(failedAfter, ZONE));
  assert.equal(stale.tone, "stale");
  assert.equal(stale.text, "The last retrieval, at 14 Oct 2026, 13:00 (Asia/Jerusalem), failed: HTTP 503 from the " +
    "publisher. The entries shown are from 14 Oct 2026, 12:00 (Asia/Jerusalem) (2 entries held).");
  const never: NewsSource = { ...base, state: "never_refreshed", stale: false, last_success_at: null, last_attempt: null, entries: 0 };
  assert.match(say(sourceStateText(never, ZONE)).text, /^Not retrieved yet\. .*requests nothing from a publisher\.$/);
  const failed: NewsSource = { ...never, state: "failed", last_attempt: failedAfter.last_attempt };
  assert.equal(say(sourceStateText(failed, ZONE)).text,
               "Not retrieved: the attempt at 14 Oct 2026, 13:00 (Asia/Jerusalem) failed: HTTP 503 from the publisher.");
  const unreadable: NewsSource = { ...never, state: "unreadable", note: "SYNTHETIC note." };
  assert.match(say(sourceStateText(unreadable, ZONE)).text, /could not be read.*SYNTHETIC note\.$/);
});

test("coverage names the publishers this server's feeds come from and says it is not all news", () => {
  assert.equal(say(coverageText(news.sources)), "This page covers 5 official feeds from Board of Governors of the " +
    "Federal Reserve System, U.S. Bureau of Labor Statistics, U.S. Energy Information Administration and World Trade " +
    "Organization only. It is not all news.");
  assert.deepEqual(empty.entries, []);
  assert.match(empty.notes[0], /Nothing is filled in from elsewhere/);  // An empty view stays empty: no invented entries.
});

test("filtering what is shown is by topic, feed and listing only, over entries already read", () => {
  assert.deepEqual(filtered(all.entries, NO_FILTER), all.entries);
  const energy = filtered(all.entries, { ...NO_FILTER, interest: "energy" });
  assert.ok(energy.length > 0 && energy.every((entry) => entry.topics.some((topic) => topic.interest === "energy")));
  assert.ok(energy.some((entry) => entry.source === "wto-news"));  // Found by its terms, not its feed.
  const fed = filtered(all.entries, { ...NO_FILTER, source: "fed-monetary" });
  assert.ok(fed.length === 2 && fed.every((entry) => entry.source === "fed-monetary"));
  const withRetained = [...all.entries, { ...all.entries[0], entry_id: "wto-news:00000000000000000000", listing: "retained" as const }];
  assert.equal(filtered(withRetained, { ...NO_FILTER, retained: false }).length, all.entries.length);
});

test("a search the server would refuse is said before anything is sent or counted", () => {
  assert.equal(searchProblem("natural gas"), null);
  assert.equal(searchProblem("  "), "Type at least one word to search for.");
  assert.equal(searchProblem("!!! ---"), "A search needs at least one word of letters or digits.");
  assert.equal(searchProblem("a ".repeat(9)), "A search has at most 8 words; this one has 9.");
  assert.equal(searchProblem("a".repeat(201)), "A search has at most 200 characters.");
  assert.equal(searchProblem("😀".repeat(200).replace(/^😀/, "a")), null);  // Characters are code points.
  assert.deepEqual(queryWords("ＣＰＩ rose, 0.4%"), ["cpi", "rose", "0", "4"]);
});

test("a search keeps its key only to repeat one whose reply never arrived; anything else is a new search", () => {
  let counter = 0;
  const fresh = () => `search-${++counter}`;
  const body: SearchBody = { query: "synthetic", interests: null, sources: null, listing: "current" };
  assert.equal(searchKey(null, body, fresh), "search-1");
  assert.equal(searchKey({ body, key: "search-1", confirmed: false }, body, fresh), "search-1");
  assert.equal(searchKey({ body, key: "search-1", confirmed: true }, body, fresh), "search-2");
  assert.equal(searchKey({ body, key: "search-1", confirmed: false }, { ...body, listing: "all" }, fresh), "search-3");
});

test("the paste step fills only the headline, the official address and the time the feed states; never the text", () => {
  const stated = pasteOffer(entryOf("stated"), "Board of Governors of the Federal Reserve System");
  const utc = entryOf("stated").published.utc!;
  assert.deepEqual({ ...stated.fields }, { headline: entryOf("stated").title, source_url: entryOf("stated").link,
    date: utc.slice(0, 10), time: utc.slice(11, 16), offset: "+00:00", text: "" });
  assert.ok(stated.notes.some((note) => /not the publication/.test(note)));
  const dated = pasteOffer(entryOf("date_only"), "World Trade Organization");
  assert.deepEqual([dated.fields.date, dated.fields.time, dated.fields.offset], ["2026-10-08", "", ""]);
  assert.ok(dated.notes.some((note) => /only the date/.test(note)));
  const unknown = pasteOffer(entryOf("unstated"), "U.S. Energy Information Administration");
  assert.deepEqual([unknown.fields.date, unknown.fields.time, unknown.fields.offset], ["", "", ""]);
  const seconds = pasteOffer({ ...entryOf("stated"), title_shortened: true, published: { ...entryOf("stated").published,
    utc: "2026-09-16T18:00:30+00:00" } }, "SYNTHETIC");
  assert.deepEqual([seconds.fields.time, seconds.fields.offset], ["", ""]);  // A minute-only form would move it.
  assert.ok(seconds.notes.some((note) => /shortened this headline/.test(note)));
  offerPaste(stated);
  assert.equal(peekPaste(), stated);
  clearPaste();
  assert.equal(peekPaste(), null);
  for (const offer of [stated, dated, unknown]) say(offer.notes);
});

test("limits are the server's figures: used, limit and what is left, the reset in its zone, nothing worked out", () => {
  assert.deepEqual(limits.operations.map(quotaText), ["Searches: 4 of 20 used today · 16 left",
    "Publication imports: 2 of 5 used today · 3 left", "New sources: 3 of 10 used today · 7 left",
    "Prepared analyses: 1 of 10 used today · 9 left"]);
  assert.deepEqual(storageText(limits), ["Sources held: 3 of 200", "Source text held: 2,461 of 5,000,000 bytes"]);
  assert.equal(resetText(limits), "Counts reset 15 Oct 2026, 00:00 (Asia/Jerusalem) (14 Oct 2026, 21:00 UTC).");
  assert.ok(unset.operations.every((quota) => quotaText(quota).endsWith("none allowed until the administrator sets limits")));
  say([limits.operations.map(quotaText), storageText(unset), resetText(unset)]);
});

test("each new refusal has its own title, the figures it carries, and a paste offer only where the server makes one", () => {
  const limit = say(refused("usage_limit_reached"));
  assert.equal(limit.title, "Today's limit is used");
  assert.deepEqual(limit.facts, ["20 of 20 searches used on 14 Oct 2026.",
    "The day resets 15 Oct 2026, 00:00 (Asia/Jerusalem) (14 Oct 2026, 21:00 UTC)."]);
  assert.match(say(refused("storage_limit_reached")).facts[0], /4,999,000 of the 5,000,000 bytes.*would add 2,461/);
  assert.match(say(refused("rate_limited", 429)).facts[0], /^Wait at least 20 seconds before trying again\. Nothing is tried again by itself\.$/);
  for (const code of ["import_unsupported", "publication_unavailable", "publication_unreadable", "publication_too_long",
                      "fetch_budget_reached"]) {
    assert.equal(say(refused(code)).pasteInstead, true, code);
  }
  for (const code of ["entry_changed", "publication_time_conflict", "import_in_progress", "no_usage_policy"]) {
    assert.equal(refused(code).pasteInstead, false, code);
  }
  assert.match(refused("publication_unavailable").facts.join(" "), /requested for this, so it counts/);
  assert.match(refused("import_unsupported").facts.join(" "), /Nothing was requested from the publisher and nothing was counted/);
  assert.equal(refused("no_usage_policy").next, "ask_admin");
  assert.equal(refused("account_binding_required", 428).next, "reload");
});

test("a 401 account_changed stops the tab rather than ending this account's session; the reply stays readable", async () => {
  const changed = { state: "refused" as const, status: 401, error: errors.account_changed };
  assert.equal(sessionEndedBy(changed), null);
  assert.equal(sessionEndedBy({ state: "refused", status: 401, error: errors.session_expired }), "session_expired");
  const reply = new Response(JSON.stringify(errors.account_changed), { status: 401 });
  assert.equal(await changedAccount(reply), true);
  assert.equal((await reply.json()).code, "account_changed");  // Read through a clone; the original is left intact.
  assert.equal(await changedAccount(new Response(JSON.stringify(errors.not_signed_in), { status: 401 })), false);
  assert.equal(await changedAccount(new Response(JSON.stringify(errors.account_changed), { status: 409 })), false);
  assert.equal(await changedAccount(new Response("not json", { status: 401 })), false);
});

test("interest selections compare in order; nothing the Client says carries the administrator's vocabulary", () => {
  assert.equal(sameSelection(["energy", "trade"], ["energy", "trade"]), true);
  assert.equal(sameSelection(["energy"], ["energy", "trade"]), false);
  for (const text of said) assert.doesNotMatch(text, ADMIN_ONLY, text.slice(0, 120));
});
