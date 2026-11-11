// The news part of user-api-0.4 (docs/news-usage-contract.md) against its SYNTHETIC fixtures
// (frontend/tests/fixtures/news-contract-*.json, written by tests/news_contract_fixtures.py from the data owner's real
// functions over synthetic feeds and pages): every fixture reads with its reader, tampered or contradictory payloads are
// refused, no fixture carries an administrator-only field or a model, provider or money term, refusals carry their
// fields, and the request helpers send exactly the documented requests, each naming the page's account. Owned by the
// logic conversation with src/contracts/news.ts.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";
import {
  REQUEST_KEY, newRequestKey, newsApi, readImport, readImportConfirmed, readImportCreated, readInterests,
  readInterestsSaved, readInterestsState, readLimits, readNews, readQuality, readSearch,
} from "../src/contracts/news.ts";
import { ACCOUNT_HEADER, ADMIN_ONLY_KEYS, ERROR_CODES, USER_HEADER, readError, type Read } from "../src/contracts/user.ts";

const fixtures = new URL("./fixtures/", import.meta.url);
const load = <T = Record<string, any>>(name: string): T =>
  JSON.parse(readFileSync(new URL(`news-contract-${name}.json`, fixtures), "utf8"));
const copy = <T>(value: T): T => structuredClone(value);
const problem = <T>(read: Read<T>) => (read.ok ? null : read.problem);

const READERS: Record<string, (body: unknown) => Read<unknown>> = {
  news: readNews, "news-all": readNews, "news-empty": readNews, interests: readInterests,
  "interests-none": readInterests, "interests-saved": readInterestsSaved, search: readSearch,
  "import-created": readImportCreated, import: readImport, "import-confirmed": readImportConfirmed,
  limits: readLimits, "limits-no-policy": readLimits, quality: readQuality, "quality-flagged": readQuality,
  "quality-none": readQuality,
};

test("every news fixture has a reader, and reads", () => {
  const published = readdirSync(fixtures).filter((name) => name.startsWith("news-contract-"))
    .map((name) => name.slice("news-contract-".length, -".json".length)).sort();
  assert.deepEqual(published, Object.keys(READERS).sort());
  for (const [name, read] of Object.entries(READERS)) assert.equal(problem(read(load(name))), null, name);
});

test("the fixtures show the states a page must handle", () => {
  const all = load("news-all").news;
  const states = new Set(all.entries.map((entry: any) => entry.import.state));
  assert.deepEqual([...states].sort(), ["imported", "supported", "unsupported"]);
  assert.ok(all.entries.some((entry: any) => entry.published.state === "unstated" && entry.published.utc === null));
  assert.ok(all.sources.some((source: any) => source.state === "not_requested"));
  assert.equal(load("news-empty").news.entries.length, 0);
  assert.ok(load("news-empty").news.sources.every((source: any) => source.state === "never_refreshed"));
  assert.equal(load("limits-no-policy").limits.operations.every((row: any) => row.limit === null), true);
  assert.ok(load("quality-flagged").quality.flagged > 0);
});

test("no news fixture carries an administrator-only field, a model, a provider or money", () => {
  for (const name of readdirSync(fixtures).filter((file) => file.startsWith("news-contract-"))) {
    const raw = readFileSync(new URL(name, fixtures), "utf8");
    assert.doesNotMatch(raw, /claude|sonnet|opus|haiku|anthropic|\busd\b|\$|token/i, name);
    for (const key of ADMIN_ONLY_KEYS) assert.ok(!raw.includes(`"${key}":`), `${name} carries ${key}`);
  }
  const leaked = copy(load("search"));
  leaked.entries[0].usage = { input_tokens: 1 };
  assert.match(problem(readSearch(leaked)) ?? "", /administrator-only/);
});

test("contradictory news is refused", () => {
  const news = load("news");
  const outside = copy(news);
  outside.news.entries[0].matches_interests = false;
  assert.match(problem(readNews(outside)) ?? "", /outside/);
  const timeless = copy(news);
  timeless.news.entries[0].published = { ...timeless.news.entries[0].published, state: "stated", utc: null };
  assert.match(problem(readNews(timeless)) ?? "", /publication time/);
  const imported = copy(load("news-all"));
  const entry = imported.news.entries.find((row: any) => row.import.state === "imported");
  entry.import.source_ids = [];
  assert.match(problem(readNews(imported)) ?? "", /import state/);
  const stranger = copy(news);
  stranger.news.entries[0].source = "fed-monetary";
  stranger.news.entries[0].entry_id = `wto-news:${"0".repeat(20)}`;
  assert.ok(problem(readNews(stranger)));
  const unknown = copy(news);
  unknown.news.sources[0].state = "fresh";
  assert.ok(problem(readNews(unknown)));
  const noSuccess = copy(news);
  noSuccess.news.sources[0] = { ...noSuccess.news.sources[0], state: "ok", last_success_at: null };
  assert.match(problem(readNews(noSuccess)) ?? "", /without a successful retrieval/);
  const http = copy(news);
  http.news.entries[0].link = "http://www.federalreserve.gov/x.htm";
  assert.ok(problem(readNews(http)));
});

test("interests, searches, imports, limits and checks that contradict themselves are refused", () => {
  const unordered = copy(load("interests"));
  unordered.interests.selected = ["energy", "monetary-policy"];
  assert.match(problem(readInterests(unordered)) ?? "", /order/);
  const versionless = copy(load("interests"));
  versionless.interests.version = null;
  assert.ok(problem(readInterests(versionless)));
  assert.equal(problem(readInterestsState(load("interests").interests)), null);
  const shown = copy(load("search"));
  shown.search.shown += 1;
  assert.match(problem(readSearch(shown)) ?? "", /number of entries/);
  const otherQuota = copy(load("search"));
  otherQuota.quota.operation = "import";
  assert.ok(problem(readSearch(otherQuota)));
  const sourceless = copy(load("import"));
  sourceless.import.source_id = null;
  assert.match(problem(readImport(sourceless)) ?? "", /state and source/);
  const textless = copy(load("import-created"));
  textless.import.proposed_source.text = null;
  assert.ok(problem(readImportCreated(textless)));
  const longer = copy(load("import-created"));
  longer.import.proposed_source.characters += 1;
  assert.match(problem(readImportCreated(longer)) ?? "", /characters/);
  const elsewhere = copy(load("import-confirmed"));
  elsewhere.source.source_id = "20261014T090000000000Z-000000000000";
  assert.ok(problem(readImportConfirmed(elsewhere)));
  const remainder = copy(load("limits"));
  remainder.limits.operations[0].remaining += 1;
  assert.match(problem(readLimits(remainder)) ?? "", /remainder/);
  const unset = copy(load("limits"));
  unset.limits.operations[1].limit = null;
  unset.limits.operations[1].remaining = null;
  assert.match(problem(readLimits(unset)) ?? "", /contradict/);
  const missing = copy(load("limits"));
  missing.limits.operations.pop();
  assert.ok(problem(readLimits(missing)));
  const recount = copy(load("quality-flagged"));
  recount.quality.flagged = 0;
  assert.ok(problem(readQuality(recount)));
  const rejecting = copy(load("quality"));
  rejecting.quality.rejected = [{ check: "x" }];
  assert.ok(problem(readQuality(rejecting)));
});

const NEWS_CODES = ["no_usage_policy", "usage_limit_reached", "storage_limit_reached", "fetch_budget_reached",
  "request_key_reused", "interests_changed", "rate_limited", "too_many_requests", "entry_changed", "import_unsupported",
  "publication_unavailable", "publication_time_conflict", "import_in_progress", "publication_changed",
  "import_interrupted", "publication_unreadable", "publication_too_long"];

test("every news and limits refusal reads, with the fields it carries", () => {
  // Their examples are in user-contract-errors.json, with every other code.
  const errors = JSON.parse(readFileSync(new URL("user-contract-errors.json", fixtures), "utf8")) as
    Record<string, Record<string, unknown>>;
  for (const code of NEWS_CODES) {
    const body = errors[code];
    assert.ok((ERROR_CODES as readonly string[]).includes(code) && body !== undefined, code);
    const read = readError(body);
    assert.ok(read.ok, `${code}: ${problem(read)}`);
  }
  const quotaless = { ...errors.usage_limit_reached };
  delete quotaless.quota;
  assert.ok(!readError(quotaless).ok);
  assert.ok(!readError({ ...errors.storage_limit_reached, storage: { measure: "sources", limit: 5, used: 1, adding: 1 } }).ok);
  assert.ok(!readError({ ...errors.rate_limited, retry_after_seconds: -1 }).ok);
  assert.ok(!readError({ ...errors.not_found ?? errors.entry_changed, retry_after_seconds: 3 }).ok);
  assert.equal(readInterestsState(errors.interests_changed.interests).ok, true);
  assert.equal(errors.import_unsupported.paste_instead, true);
  // An import preview's refusal says whether the publisher was contacted, which is when it counts.
  assert.equal(errors.publication_unavailable.requested, true);
  assert.equal(errors.import_unsupported.requested, false);
  const tooLong = readError(errors.publication_too_long);
  assert.ok(tooLong.ok && tooLong.value.requested === true);
  assert.ok(!readError({ ...errors.publication_unavailable, requested: "yes" }).ok);
  assert.equal(errors.no_usage_policy.requested, undefined);
});

test("the helpers send the documented requests, each naming the page's account", async () => {
  const seen: { url: string; init: RequestInit }[] = [];
  const replies: Record<string, unknown> = {
    "/api/user/news?scope=all": load("news-all"), "/api/user/news/interests": load("interests-saved"),
    "/api/user/news/searches": load("search"), "/api/user/news/imports": load("import-created"),
    "/api/user/limits": load("limits"),
  };
  const fetcher = async (url: string, init: RequestInit) => {
    seen.push({ url, init });
    const reply = replies[url] ?? (url.endsWith("/confirmation") ? load("import-confirmed")
      : url.endsWith("/quality") ? load("quality") : url.includes("/imports/") ? load("import") : load("interests"));
    return new Response(JSON.stringify(reply), { status: 200 });
  };
  const api = newsApi(fetcher, { account: "u-0000000000000001" });
  const results = [
    await api.news("all"), await api.interests(), await api.saveInterests(["monetary-policy"], null),
    await api.search({ query: "synthetic", interests: null, sources: null, listing: "all", request_key: "search-0001" }),
    await api.previewImport(`fed-monetary:${"a".repeat(20)}`, "b".repeat(64)), await api.importPreview("imp-0123456789abcdef"),
    await api.confirmImport("imp-0123456789abcdef", "c".repeat(64)), await api.limits(), await api.quality("x/y"),
  ];
  assert.ok(results.every((reply) => reply.state === "ok"), JSON.stringify(results.map((reply) => reply.state)));
  assert.deepEqual(seen.map((sent) => `${sent.init.method} ${sent.url}`), [
    "GET /api/user/news?scope=all", "GET /api/user/news/interests", "POST /api/user/news/interests",
    "POST /api/user/news/searches", "POST /api/user/news/imports", "GET /api/user/news/imports/imp-0123456789abcdef",
    "POST /api/user/news/imports/imp-0123456789abcdef/confirmation", "GET /api/user/limits",
    "GET /api/user/analyses/x%2Fy/quality"]);
  for (const sent of seen) {
    const headers = sent.init.headers as Record<string, string>;
    assert.equal(headers[ACCOUNT_HEADER], "u-0000000000000001", sent.url);
    assert.equal(headers[USER_HEADER], sent.init.method === "POST" ? "1" : undefined, sent.url);
  }
  const bodies = seen.filter((sent) => sent.init.method === "POST").map((sent) => JSON.parse(String(sent.init.body)));
  assert.deepEqual(bodies, [
    { interests: ["monetary-policy"], expected_version: null },
    { query: "synthetic", interests: null, sources: null, listing: "all", request_key: "search-0001" },
    { entry_id: `fed-monetary:${"a".repeat(20)}`, version_sha256: "b".repeat(64) },
    { text_sha256: "c".repeat(64), confirm: true }]);
  assert.match(newRequestKey(), REQUEST_KEY);
  assert.notEqual(newRequestKey(), newRequestKey());
});
