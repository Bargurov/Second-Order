// The stories part of user-api-0.5 (docs/news-stories-contract.md) against its SYNTHETIC fixtures
// (frontend/tests/fixtures/stories-contract-*.json, written by tests/stories_contract_fixtures.py from the server's real
// functions over synthetic publishers and feeds): every fixture reads with its reader, tampered or contradictory payloads
// are refused, no fixture carries an administrator-only field or a model, provider or money term, and the request
// helpers send exactly the documented requests, each naming the page's account, and never retry.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";
import {
  readDeeperDone, readDeeperPreview, readStories, readStory, readTopic, readTopics, storiesApi,
} from "../src/contracts/stories.ts";
import { ACCOUNT_HEADER, ADMIN_ONLY_KEYS, USER_HEADER, readError, type Read } from "../src/contracts/user.ts";
import { recordingFetcher } from "../src/client/testing/recordingFetcher.ts";

const fixtures = new URL("./fixtures/", import.meta.url);
const load = <T = Record<string, any>>(name: string): T =>
  JSON.parse(readFileSync(new URL(`stories-contract-${name}.json`, fixtures), "utf8"));
const copy = <T>(value: T): T => structuredClone(value);
const problem = <T>(read: Read<T>) => (read.ok ? null : read.problem);

const READERS: Record<string, (body: unknown) => Read<unknown>> = {
  hot: readStories, coverage: readStories, latest: readStories, interests: readStories, empty: readStories, story: readStory,
  "story-nobrief": readStory, "story-notime": readStory, "story-merged": readStory, topics: readTopics,
  topic: readTopic, deeper: readDeeperPreview, "deeper-existing": readDeeperPreview, "deeper-done": readDeeperDone,
  "story-text": readStory, "deeper-text": readDeeperPreview, "latest-text": readStories,
  "story-outside": readStory, "hot-unassessed": readStories, "story-indexed": readStory, "story-claims": readStory,
};

test("a brief that records who says what reads, and claims that contradict the brief are refused", () => {
  const page = load("story-claims");
  assert.equal(problem(readStory(page)), null);
  const brief = page.story.brief;
  assert.equal(brief.brief_version, "story-brief-0.4");
  assert.equal(brief.economics.summary.stage, "procedure");
  assert.equal(brief.economics.summary.stage_label, "Procedure opened, no decision on a measure");
  assert.deepEqual(brief.claims.claims.map((row: any) => [row.id, row.modality, row.facts]),
    [["k1", "asserted", [1]], ["k2", "conditional", [2]]]);
  assert.equal(brief.claims.claims[1].condition, "only if increased imports are found to cause serious injury");
  assert.match(brief.economics.figures[0].claim_label, /^conditional: only if/);
  assert.match(brief.economics.summary.why_it_matters, /\(conditional: only if increased imports/);
  const broken: [string, (value: any) => void][] = [
    ["a fact citing a claim the brief does not record", (value) => { value.content.facts[0].claims = ["k9"]; }],
    ["facts citing claims while the brief records none", (value) => { delete value.content.claims; delete value.claims; }],
    ["claims shown that the brief does not record", (value) => {
      delete value.content.claims; for (const fact of value.content.facts) delete fact.claims; }],
    ["a conditional claim without its condition", (value) => { value.content.claims[1].condition = null; }],
    ["a view that changes a claim's words", (value) => { value.claims.claims[1].quote = "SYNTHETIC: a duty will apply"; }],
    ["a view linking a claim to a fact that does not cite it", (value) => { value.claims.claims[0].facts = [2]; }],
    ["claims numbered out of order", (value) => { value.content.claims[0].id = "k2"; }],
  ];
  for (const [why, change] of broken) {
    const tampered = structuredClone(page);
    change(tampered.story.brief);
    assert.equal(readStory(tampered).ok, false, why);
  }
  const earlier = load("story");  // A brief that records no claims shows none, as before.
  assert.equal(earlier.story.brief.claims, undefined);
  assert.ok(earlier.story.brief.content.facts.every((fact: any) => fact.claims === undefined));
  const view = readFileSync(new URL("../src/client/components/StoryView.tsx", import.meta.url), "utf8");
  for (const hook of [/data-claims/, /data-claim-condition/, /data-fact-claim=/, /data-figure-claim/]) {
    assert.match(view, hook);
  }
});

test("a claim view keeps the recorded speaker, source and complete fact citations", () => {
  const broken: [string, (value: any) => void][] = [
    ["a different speaker", (value) => { value.holder_name = "A different speaker"; }],
    ["a missing speaker", (value) => { delete value.holder_name; }],
    ["a different source", (value) => { value.source = "context:somewhere-else"; }],
    ["a missing source", (value) => { delete value.source; }],
    ["a missing report citation", (value) => { value.reports = []; }],
    ["another report citation", (value) => { value.reports = ["unknown-report"]; }],
    ["a repeated report citation", (value) => { value.reports.push(value.reports[0]); }],
    ["an omitted fact citation", (value) => { value.facts = []; }],
    ["a repeated fact citation", (value) => { value.facts.push(value.facts[0]); }],
  ];
  for (const [why, change] of broken) {
    const page = load("story-claims");
    change(page.story.brief.claims.claims[0]);
    assert.equal(readStory(page).ok, false, why);
  }
});

test("a story covered through the news index counts its indexed publishers apart from their origins", () => {
  const story = load("story-indexed").story;
  const indexed = story.sources.filter((row: any) => row.entry_id.startsWith("gdelt-index:"));
  assert.equal(indexed.length, 3);
  assert.ok(indexed.every((row: any) => row.use === "listed" && /GDELT Project/.test(row.attribution) &&
    row.excerpt === null));
  assert.equal(story.coverage.publishers, 4);
  assert.equal(story.coverage.origins, 3);
  assert.ok(story.coverage.uncertain >= 2);
  assert.ok(story.coverage.units.some((unit: any) => unit.counted_together_because.includes("the same headline")));
});

test("every stories fixture has a reader, and reads", () => {
  const published = readdirSync(fixtures).filter((name) => name.startsWith("stories-contract-"))
    .map((name) => name.slice("stories-contract-".length, -".json".length)).sort();
  assert.deepEqual(published, Object.keys(READERS).sort());
  for (const [name, read] of Object.entries(READERS)) assert.equal(problem(read(load(name))), null, name);
});

test("the coverage view reads and is requested explicitly with the account binding", async () => {
  const body = copy(load("hot"));
  body.stories.view = "coverage";
  body.stories.rank.order_version = "news-coverage-order-0.1";
  assert.equal(problem(readStories(body)), null);
  const request = recordingFetcher(() => ({status: 200, body}));
  const reply = await storiesApi(request.fetcher, { account: "u-0000000000000001" }).stories("coverage");
  assert.equal(reply.state, "ok");
  assert.equal(request.requests.length, 1);
  assert.equal(request.requests[0].path, "/api/user/news/stories?view=coverage");
  assert.equal(request.requests[0].method, "GET");
  assert.equal(request.requests[0].headers[ACCOUNT_HEADER.toLowerCase()], "u-0000000000000001");
});

test("the fixtures show the states a page must handle", () => {
  const hot = load("hot").stories;
  assert.ok(hot.stories.length > 0 && hot.stories.every((story: any) => story.synthetic));
  assert.ok(hot.stories.some((story: any) => story.brief.state === "published" && story.brief.summary));
  assert.ok(hot.stories.some((story: any) => story.brief.state === "none" && story.excerpt));
  assert.ok(hot.stories.some((story: any) => story.signals.some((row: any) => row.signal === "coverage")));
  assert.ok(load("latest").stories.stories.length >= hot.stories.length);
  assert.ok(load("empty").stories.notes[0].startsWith("No stories have been put together"));
  const story = load("story").story;
  assert.equal(story.brief_state, "published");
  assert.ok(story.sources.some((row: any) => row.use === "material"));
  assert.equal(story.coverage.repeats, 1);  // The wire copy counts once.
  assert.ok(story.related.length > 0 && story.topics.length > 0);
  assert.equal(load("story-nobrief").story.brief, null);
  assert.equal(load("story-notime").story.deeper.available, false);
  assert.equal(load("story-merged").story.merged, true);
  assert.equal(load("topic").topic.timeline.length, 3);
  assert.equal(load("deeper").deeper.existing, null);
  assert.ok(load("deeper-existing").deeper.existing.analyses.length > 0);
  assert.equal(load("deeper-done").deeper.analysis.state, "prepared");
});

test("news-rank-0.4's breadth, breaking, relevance and importance signals read; older versions do not", () => {
  const body = load("hot");
  assert.equal(body.stories.rank.rank_version, "news-rank-0.4");
  const breaking = copy(body);
  breaking.stories.stories[0].signals.push({ signal: "breaking", text: "A new development of high importance." });
  assert.equal(problem(readStories(breaking)), null);
  assert.ok(body.stories.stories.some((story: any) => story.signals.some((row: any) => row.signal === "importance")));
  const subject = copy(body);
  subject.stories.stories[0].signals.push({ signal: "no_subject", text: "It names none of the news's subjects." });
  assert.ok(problem(readStories(subject)));
  const older = load("hot");
  older.stories.rank.rank_version = "news-rank-0.3";
  assert.ok(problem(readStories(older)));
});

test("only established relevance is listed; the rest waits in view, and what is left out is counted", () => {
  const unassessed = load("hot-unassessed").stories;
  assert.equal(unassessed.stories.length, 0);
  assert.ok(unassessed.awaiting.length > 0 && unassessed.awaiting.every((story: any) =>
    story.relevance.state === "pending"));
  const latest = load("latest").stories;
  assert.ok(latest.stories.every((story: any) => story.relevance.state === "relevant"));
  assert.equal(latest.left_out.outside_scope, 1);
  const outside = load("story-outside").story;
  assert.equal(outside.relevance.state, "outside_scope");
  assert.equal(outside.deeper.available, false);
  assert.ok(!latest.stories.some((story: any) => story.story_id === outside.story_id));
  const relevant = load("story").story.relevance;
  assert.equal(relevant.state, "relevant");
  assert.ok(relevant.dimensions.length > 0 && relevant.basis_label);
  const cases: [string, (body: any) => void][] = [
    ["an unassessed story listed as news", (body) => { body.stories.stories.push(body.stories.awaiting[0]); }],
    ["a relevant story awaiting", (body) => { body.stories.awaiting[0].relevance.state = "relevant"; }],
    ["a story both listed and awaiting", (body) => { body.stories.awaiting.push(body.stories.stories[0]); }],
    ["no count of what is left out", (body) => { delete body.stories.left_out; }],
  ];
  for (const [name, change] of cases) {
    const body = copy(load("latest"));
    if (body.stories.awaiting.length === 0) body.stories.awaiting.push({ ...copy(body.stories.stories[0]),
      story_id: "story-00000000000000aa", relevance: { state: "pending", statement: "Not assessed yet." },
      signals: [] });
    change(body);
    assert.ok(problem(readStories(body)), name);
  }
  const pages: [string, (story: any) => void][] = [
    ["dimensions for a story outside the scope", (story) => { story.relevance.dimensions = [{ dimension: "trade",
      how: "x" }]; }],
    ["a deeper analysis outside the scope", (story) => { story.deeper = { available: true, material_reports: 1,
      reason: null }; }],
    ["no one who decided", (story) => { story.relevance.basis = null; }],
    ["an unknown dimension", (story) => { story.relevance.state = "relevant"; story.relevance.dimensions = [
      { dimension: "sentiment", how: "x" }]; }],
  ];
  for (const [name, change] of pages) {
    const body = copy(load("story-outside"));
    change(body.story);
    assert.ok(problem(readStory(body)), name);
  }
});

test("no stories fixture carries an administrator-only field, a model, a provider, money or an operator", () => {
  for (const name of readdirSync(fixtures).filter((file) => file.startsWith("stories-contract-"))) {
    const raw = readFileSync(new URL(name, fixtures), "utf8");
    assert.doesNotMatch(raw, /claude|sonnet|opus|haiku|anthropic|\busd\b|\$|token|fixture-admin|fixture-key|idempotency/i,
                        name);
    for (const key of ADMIN_ONLY_KEYS) assert.ok(!raw.includes(`"${key}":`), `${name} carries ${key}`);
  }
  const leaked = copy(load("story"));
  leaked.story.brief.preparation = { model: "x" };
  assert.match(problem(readStory(leaked)) ?? "", /administrator-only/);
});

test("contradictory stories are refused", () => {
  const cases: [string, (body: any) => void][] = [
    ["a published brief without its summary", (body) => { body.stories.stories[0].brief = { state: "published", summary: null }; }],
    ["a brief and a feed excerpt together", (body) => {
      const story = body.stories.stories.find((row: any) => row.brief.state === "published");
      story.excerpt = { publisher: "X", text: "y" };
    }],
    ["first after latest", (body) => { body.stories.stories[0].first_at = "2099-01-01T00:00:00+00:00"; }],
    ["an unknown signal", (body) => { body.stories.stories[0].signals = [{ signal: "popularity", text: "x" }]; }],
    ["a story twice", (body) => { body.stories.stories.push(body.stories.stories[0]); }],
    ["an unknown view", (body) => { body.stories.view = "popular"; }],
  ];
  for (const [name, change] of cases) {
    const body = copy(load("hot"));
    change(body);
    assert.ok(problem(readStories(body)), name);
  }
  const interests = copy(load("interests"));
  interests.stories.interests = ["technology"];
  assert.match(problem(readStories(interests)) ?? "", /outside/);
});

test("an AI-assisted, unreviewed brief reads, and a card says whether its brief is current", () => {
  const body = copy(load("story"));
  Object.assign(body.story.brief, { method: "assisted", authorship: "ai_assistant", method_label: "Written with an AI "
    + "assistant from the material below.", review: { state: "not_reviewed", statement: "No editor has read it." } });
  assert.equal(problem(readStory(body)), null);
  const hot = copy(load("hot"));
  const briefed = hot.stories.stories.find((story: any) => story.brief.state === "published");
  assert.equal(briefed.brief.current, true);
  briefed.brief.current = null;
  assert.ok(problem(readStories(hot)));
  const waiting = copy(load("hot"));
  waiting.stories.stories.find((story: any) => story.brief.state === "none").brief.current = false;
  assert.ok(problem(readStories(waiting)));
});

test("retained publication texts read: full, partial and failed sources, and full-text deeper material", () => {
  const story = load("story-text").story;
  const states = story.sources.map((row: any) => row.text.state).sort();
  assert.deepEqual(states, ["full_text", "full_text"]);
  assert.ok(story.sources.every((row: any) => row.text.characters > 0 && row.text.retrieved_at));
  const deeper = load("deeper-text").deeper;
  assert.equal(deeper.material.coverage, "full_text");
  assert.ok(deeper.material.reports.every((row: any) => row.text.state === "full_text" && /^[0-9a-f]{64}$/.test(
    row.text.text_sha256)));
  assert.match(deeper.source.text, /What this is: the text of 2 publications/);
  const latest = load("latest-text").stories.stories;
  const byTitle = (word: string) => latest.find((row: any) => row.title.includes(word));
  assert.ok(byTitle("cannot be read") && byTitle("holding a table"));
  const cases: [string, (body: any) => void][] = [
    ["a full text without its size", (body) => { body.story.sources[0].text.characters = null; }],
    ["a held text in an unknown state", (body) => { body.story.sources[0].text.state = "cached"; }],
  ];
  for (const [name, change] of cases) {
    const body = copy(load("story-text"));
    change(body);
    assert.ok(problem(readStory(body)), name);
  }
  const partial = copy(load("deeper-text"));
  partial.deeper.material.reports[0].text.state = "partial_text";
  assert.ok(problem(readDeeperPreview(partial)), "a partial text without its reason");
  const claimed = copy(load("deeper"));
  claimed.deeper.material.coverage = "full_text";
  assert.ok(problem(readDeeperPreview(claimed)), "full text claimed without any text");
});

test("a story page that contradicts itself is refused", () => {
  const cases: [string, (story: any) => void][] = [
    ["a published state without a brief", (story) => { story.brief = null; }],
    ["a fact citing a report the material lacks", (story) => { story.brief.content.facts[0].reports = ["x-y:0123456789abcdef0123"]; }],
    ["a material source marked as listed only", (story) => { story.sources[0].use = "listed"; }],
    ["deeper available with a reason", (story) => { story.deeper.reason = "x"; }],
    ["a non-https source link", (story) => { story.sources[0].link = "http://example.org/x"; }],
    ["another number of sources", (story) => { story.sources.pop(); }],
    ["a merged mark on its own address", (story) => { story.merged = true; }],
    ["a synthetic brief unmarked", (story) => { story.brief.method = "synthetic"; }],
    ["an AI-assisted brief said to be written by an editor", (story) => {
      Object.assign(story.brief, { method: "assisted", authorship: "ai_assistant" });
      story.brief.review = { state: "written_by_editor", statement: "Written by an editor." }; }],
    ["a method whose authorship is another", (story) => { story.brief.method = "model"; }],
    ["a stale brief without its update note", (story) => { story.brief.current = false; }],
    ["a current brief with an update note", (story) => { story.brief.update_note = "x"; }],
    ["an unknown review state", (story) => { story.brief.review.state = "approved"; }],
  ];
  for (const [name, change] of cases) {
    const body = copy(load("story"));
    change(body.story);
    assert.ok(problem(readStory(body)), name);
  }
});

test("Go deeper's preview and reply are refused when they contradict themselves", () => {
  const preview = copy(load("deeper"));
  preview.deeper.source.characters += 1;
  assert.ok(problem(readDeeperPreview(preview)));
  const unavailable = copy(load("deeper"));
  unavailable.deeper.available = false;
  assert.ok(problem(readDeeperPreview(unavailable)));
  const done = copy(load("deeper-done"));
  done.created = !done.created;
  assert.ok(problem(readDeeperDone(done)));
  const other = copy(load("deeper-done"));
  other.deeper.analysis.source.source_id = "cap-0000000000000000";
  assert.ok(problem(readDeeperDone(other)));
});

test("the refusals of Go deeper read", () => {
  const errors = JSON.parse(readFileSync(new URL("user-contract-errors.json", fixtures), "utf8"));
  for (const code of ["story_changed", "deeper_unavailable", "newsroom_unreadable"]) {
    assert.equal(problem(readError(errors[code])), null, code);
  }
});

test("the helpers send the documented requests, each naming the page's account, and never retry", async () => {
  const answers: Record<string, unknown> = {
    "/api/user/news/stories?view=hot": load("hot"), [`/api/user/news/stories/${load("story").story.story_id}`]: load("story"),
    "/api/user/news/topics": load("topics"), [`/api/user/news/topics/${load("topic").topic.topic_id}`]: load("topic"),
    [`/api/user/news/stories/${load("deeper").deeper.story_id}/deeper`]: load("deeper"),
  };
  const { fetcher, requests } = recordingFetcher((request) => request.method === "POST"
    ? { status: 201, body: load("deeper-done") } : { status: 200, body: answers[request.path] ?? {} });
  const api = storiesApi(fetcher, { account: "u-0000000000000001" });
  assert.equal((await api.stories("hot")).state, "ok");
  assert.equal((await api.story(load("story").story.story_id)).state, "ok");
  assert.equal((await api.topics()).state, "ok");
  assert.equal((await api.topic(load("topic").topic.topic_id)).state, "ok");
  const preview = load("deeper").deeper;
  assert.equal((await api.deeper(preview.story_id)).state, "ok");
  assert.equal((await api.goDeeper(preview.story_id, preview.material_sha256, "low")).state, "ok");
  assert.equal(requests.length, 6);
  assert.ok(requests.every((row) => row.headers[ACCOUNT_HEADER.toLowerCase()] === "u-0000000000000001"));
  assert.deepEqual(requests.map((row) => row.method), ["GET", "GET", "GET", "GET", "GET", "POST"]);
  const post = requests[5];
  assert.equal(post.headers[USER_HEADER.toLowerCase()], "1");
  assert.deepEqual(post.body, { material_sha256: preview.material_sha256, effort: "low" });
  const lost = recordingFetcher(() => "no-reply");
  const reply = await storiesApi(lost.fetcher, { account: "u-0000000000000001" })
    .goDeeper(preview.story_id, preview.material_sha256, "low");
  assert.equal(reply.state, "unconfirmed");
  assert.equal(lost.requests.length, 1);  // Never retried.
});
