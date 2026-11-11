// The user contract (user-api-0.4) against its SYNTHETIC fixtures (frontend/tests/fixtures/user-contract-*.json):
// every published fixture reads with its reader, tampered or contradictory payloads are refused, no fixture carries an
// administrator-only field or a model, provider or money term, and the request helpers send exactly the documented
// requests. Owned by the logic conversation with src/contracts/user.ts.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";
import {
  ACCOUNT_HEADER, ADMIN_ONLY_KEYS, ERROR_CODES, USER_CONTRACT, USER_HEADER, SESSION_HEADER, approvalFor, bindingRefusal,
  codePoints, readAccount,
  readAnalyses, readAnalysis, readError, readExport, readPrepared, readQuoteIssued, readReviewSaved, readRun,
  readSession, readSourceCreated, readSourceDetail, readSources, userApi, type Analysis, type Quote, type Read,
} from "../src/contracts/user.ts";

const fixtures = new URL("./fixtures/", import.meta.url);
const load = <T = Record<string, unknown>>(name: string): T =>
  JSON.parse(readFileSync(new URL(`user-contract-${name}.json`, fixtures), "utf8"));
const copy = <T>(value: T): T => structuredClone(value);
const problem = <T>(read: Read<T>) => (read.ok ? null : read.problem);

const READERS: Record<string, (body: unknown) => Read<unknown>> = {
  "session-signed-in": readSession, "session-signed-out": readSession, "session-expired": readSession,
  "session-local-operator": readSession, account: readAccount, "account-unavailable": readAccount,
  "account-unallocated": readAccount,
  "source-created": readSourceCreated, sources: readSources, "source-detail": readSourceDetail,
  "analysis-prepared": readPrepared, quote: readQuoteIssued, "analysis-quoted": readAnalysis,
  "analysis-running": readAnalysis, "run-recorded": readRun, "run-duplicate": readRun,
  "review-saved": readReviewSaved, "analysis-recorded": readAnalysis, export: readExport,
  "analysis-no-finding": readAnalysis, "analysis-declined": readAnalysis, "analysis-invalid": readAnalysis,
  "analysis-failed": readAnalysis, "analysis-unresolved": readAnalysis, "analysis-not-sent": readAnalysis,
  analyses: readAnalyses,
};

test("every published fixture has a reader, and reads", () => {
  const published = readdirSync(fixtures).filter((name) => name.startsWith("user-contract-") && name !== "user-contract-errors.json")
    .map((name) => name.slice("user-contract-".length, -".json".length)).sort();
  assert.deepEqual(published, Object.keys(READERS).sort());
  for (const [name, read] of Object.entries(READERS)) assert.equal(problem(read(load(name))), null, name);
});

test("every error code has a readable example, with its extra fields", () => {
  const errors = load<Record<string, unknown>>("errors");
  assert.deepEqual(Object.keys(errors).sort(), [...ERROR_CODES].sort());
  for (const [code, body] of Object.entries(errors)) {
    const read = readError(body);
    assert.ok(read.ok, code);
    assert.equal(read.ok && read.value.code, code);
  }
  assert.ok(readError({ contract: USER_CONTRACT, code: "unknown_code", detail: "x" }).ok === false);
  assert.ok(readError({ contract: USER_CONTRACT, code: "forbidden", detail: "" }).ok === false);
});

test("no fixture carries an administrator-only field, a model, a provider or money", () => {
  for (const name of readdirSync(fixtures).filter((file) => file.startsWith("user-contract-"))) {
    const raw = readFileSync(new URL(name, fixtures), "utf8");
    assert.doesNotMatch(raw, /claude|sonnet|opus|haiku|anthropic|\busd\b|\$|token/i, name);
    for (const key of ADMIN_ONLY_KEYS) assert.ok(!raw.includes(`"${key}":`), `${name} carries ${key}`);
  }
});

test("a payload with an administrator-only field at any depth is refused", () => {
  const recorded = load<{ analysis: Analysis }>("analysis-recorded");
  for (const key of ["model", "usage", "planning_estimate_usd", "provider_request_id", "request"]) {
    const leaked = copy(recorded) as unknown as { analysis: { result: Record<string, unknown> } };
    leaked.analysis.result[key] = key === "usage" ? { input_tokens: 1 } : "x";
    assert.match(problem(readAnalysis(leaked)) ?? "", /administrator-only field/, key);
  }
  const account = { ...load("account"), model: "x" };
  assert.match(problem(readAccount(account)) ?? "", /administrator-only/);
});

test("another contract version, mode or role is not read; user-api-0.4 to 0.1 payloads still read", () => {
  assert.match(problem(readAccount({ ...load("account"), contract: "user-api-0.6" })) ?? "", /contract/);
  assert.equal(problem(readAccount({ ...load("account"), contract: "user-api-0.5" })), null);
  assert.equal(problem(readAccount({ ...load("account"), contract: "user-api-0.4" })), null);
  assert.equal(problem(readAccount({ ...load("account"), contract: "user-api-0.2" })), null);
  const older = load<Record<string, Record<string, unknown>>>("account-unavailable");
  delete older.analysis.reasons;
  assert.equal(problem(readAccount({ ...older, contract: "user-api-0.1" })), null);
  assert.match(problem(readSession({ ...load("session-signed-in"), mode: "dev" })) ?? "", /mode/);
  const operator = load<Record<string, Record<string, unknown>>>("session-local-operator");
  operator.user.role = "user";
  assert.match(problem(readSession(operator)) ?? "", /operator/);
  const signedOut = { ...load("session-signed-out"), user: load<Record<string, unknown>>("session-signed-in").user };
  assert.ok(problem(readSession(signedOut)));
});

test("the missing steps agree with the availability, in the server's order", () => {
  const unavailable = load<{ analysis: Record<string, unknown> }>("account-unallocated");
  assert.equal(unavailable.analysis.reason, "no_credits_allocated");
  const cases: [string, (analysis: Record<string, unknown>) => void][] = [
    ["first is not the reason", (a) => { a.reasons = [{ reason: "no_daily_limit", detail: "x" }]; }],
    ["empty while unavailable", (a) => { a.reasons = []; }],
    ["unknown reason", (a) => { a.reasons = [{ reason: "no_money", detail: "x" }]; }],
    ["out of order", (a) => { a.reasons = [a.reasons && (a.reasons as unknown[])[0],
                                           { reason: "no_daily_limit", detail: "Set a limit." }]; }],
  ];
  for (const [name, change] of cases) {
    const tampered = structuredClone(unavailable);
    change(tampered.analysis);
    assert.ok(problem(readAccount(tampered)), name);
  }
  const ready = load<{ analysis: Record<string, unknown> }>("account");
  ready.analysis.reasons = [{ reason: "no_daily_limit", detail: "x" }];
  assert.ok(problem(readAccount(ready)));
});

test("an allowance whose remainder does not follow from its limit and use is refused", () => {
  const account = load<{ daily: Record<string, unknown> }>("account");
  account.daily.remaining = 2;
  assert.match(problem(readAccount(account)) ?? "", /remainder/);
  const unlimited = load<{ daily: Record<string, unknown> }>("account-unavailable");
  unlimited.daily.remaining = 0;
  assert.ok(problem(readAccount(unlimited)));
  const efforts = load<{ efforts: unknown[] }>("account");
  efforts.efforts.reverse();
  assert.match(problem(readAccount(efforts)) ?? "", /order/);
});

test("a quoted passage must sit at its recorded place in the source text", () => {
  const recorded = load<{ analysis: Analysis }>("analysis-recorded");
  const quotes = recorded.analysis.result!.analysis!.established.flatMap((item) => item.quotes);
  for (const quote of quotes) {
    assert.equal(codePoints(recorded.analysis.source.text, quote.start, quote.end), quote.source_passage);
  }
  assert.ok(quotes.some((quote) => quote.match === "normalized" && quote.text !== quote.source_passage));
  const moved = copy(recorded);
  moved.analysis.result!.analysis!.established[0].quotes[0].start += 1;
  assert.match(problem(readAnalysis(moved)) ?? "", /recorded place/);
  const edited = copy(recorded);
  edited.analysis.source.text = edited.analysis.source.text.replace("rose", "fell");
  assert.ok(problem(readAnalysis(edited)));
});

test("a Go deeper quote names its report, publisher and part, and a malformed attribution is refused", () => {
  const recorded = load<{ analysis: Analysis }>("analysis-recorded");
  const attributed = copy(recorded);
  attributed.analysis.result!.analysis!.established[0].quotes[0].evidence =
    { report: 2, publisher: "Synthetic Ledger", part: "excerpt" };
  assert.equal(problem(readAnalysis(attributed)), null);
  for (const evidence of [{ report: 0, publisher: "Synthetic Ledger", part: "excerpt" },
    { report: 1, publisher: "", part: "excerpt" }, { report: 1, publisher: "Synthetic Ledger", part: "credit" },
    { report: 1, publisher: "Synthetic Ledger" }, null]) {
    const bad = copy(recorded);
    (bad.analysis.result!.analysis!.established[0].quotes[0] as unknown as Record<string, unknown>).evidence = evidence;
    assert.match(problem(readAnalysis(bad)) ?? "", /attribution/, JSON.stringify(evidence));
  }
});

test("states, charges, quotes, results and reviews must agree", () => {
  const recorded = load<{ analysis: Analysis }>("analysis-recorded");
  const cases: [string, (analysis: Analysis) => void, RegExp][] = [
    ["charged above reserved", (a) => { a.charge!.credits_charged = 7; }, /add up/],
    ["recorded without charge", (a) => { a.charge = null; }, /cannot have this charge/],
    ["recorded without result", (a) => { a.result = null; }, /result/],
    ["result without fingerprint", (a) => { a.result_sha256 = null; }, /fingerprint/],
    ["outcome against interpretation", (a) => { a.result!.outcome = "no_additional_finding"; }, /disagree/],
    ["interpretation names a missing statement", (a) => { a.result!.analysis!.interpretation.based_on = [9]; }, /do not exist/],
    ["unknown state", (a) => { (a as { state: string }).state = "done"; }, /not readable/],
    ["broken review chain", (a) => { a.reviews[0].parent_review_id = "x".repeat(64); }, /review/],
    ["quote on a recorded analysis", (a) => { a.quote = load<{ quote: Quote }>("quote").quote; }, /Only a prepared/],
  ];
  for (const [name, change, expected] of cases) {
    const tampered = copy(recorded);
    change(tampered.analysis);
    assert.match(problem(readAnalysis(tampered)) ?? "", expected, name);
  }
  const prepared = load<{ analysis: Analysis }>("analysis-quoted");
  const otherEffort = copy(prepared);
  otherEffort.analysis.quote!.effort = "low";
  assert.match(problem(readAnalysis(otherEffort)) ?? "", /another analysis or Effort/);
  const withResult = copy(prepared);
  withResult.analysis.result = recorded.analysis.result;
  assert.ok(problem(readAnalysis(withResult)));
  const returned = load<{ analysis: Analysis }>("analysis-not-sent");
  returned.analysis.charge!.credits_charged = 1;
  returned.analysis.charge!.credits_returned = 1;
  assert.ok(problem(readAnalysis(returned)));
  const running = load<{ analysis: Analysis }>("analysis-running");
  running.analysis.charge!.credits_charged = 6;
  assert.match(problem(readAnalysis(running)) ?? "", /unsettled/);
});

test("a run reply never shows an analysis that did not run, and a saved review is the latest version", () => {
  const run = load<Record<string, unknown>>("run-recorded");
  assert.ok(problem(readRun({ ...run, analysis: load<{ analysis: Analysis }>("analysis-prepared").analysis })));
  assert.ok(problem(readRun({ ...run, duplicate: "no" })));
  const saved = load<{ review: Record<string, unknown> }>("review-saved");
  saved.review.notes = "edited";
  assert.match(problem(readReviewSaved(saved)) ?? "", /latest version/);
  const listing = load<{ analyses: Record<string, unknown>[] }>("analyses");
  listing.analyses[0].outcome = null;
  assert.match(problem(readAnalyses(listing)) ?? "", /outcome/);
});

test("the approval repeats the quote exactly", () => {
  const { quote } = load<{ quote: Quote }>("quote");
  assert.deepEqual(approvalFor(quote), { quote_id: quote.quote_id, effort: "high", credits: 6, approve: true });
});

function transport(status: number, body: unknown, seen: { url: string; init: RequestInit }[]) {
  return async (url: string, init: RequestInit) => {
    seen.push({ url, init });
    return new Response(body === undefined ? "not json" : JSON.stringify(body), { status });
  };
}

test("reads are plain GETs; writes are JSON POSTs with the route's header, to the documented paths", async () => {
  const seen: { url: string; init: RequestInit }[] = [];
  const api = userApi(transport(200, load("account"), seen));
  await api.account();
  assert.equal(seen[0].url, "/api/user/account");
  assert.equal(seen[0].init.method, "GET");
  assert.equal(seen[0].init.body, undefined);
  assert.equal((seen[0].init.headers as Record<string, string>)[USER_HEADER], undefined);

  const posts = userApi(transport(201, load("quote"), seen));
  const quoted = await posts.quote("a/b c");
  assert.equal(quoted.state, "ok");
  const post = seen[1];
  assert.equal(post.url, "/api/user/analyses/a%2Fb%20c/quotes");
  assert.equal(post.init.method, "POST");
  assert.equal(post.init.credentials, "same-origin");
  assert.equal(post.init.body, "{}");
  assert.equal((post.init.headers as Record<string, string>)[USER_HEADER], "1");
  assert.equal((post.init.headers as Record<string, string>)["Content-Type"], "application/json");

  const sessions = userApi(transport(200, load("session-signed-in"), seen));
  await sessions.signIn("reader-a", "pw");
  assert.equal(seen[2].url, "/api/session/login");
  assert.equal((seen[2].init.headers as Record<string, string>)[SESSION_HEADER], "1");
  assert.deepEqual(JSON.parse(String(seen[2].init.body)), { username: "reader-a", password: "pw" });
  assert.equal(posts.exportHref("x.y"), "/api/user/analyses/x.y/export");
});

test("a page's helpers name its account on user reads, writes and sign-out, never on the session or sign-in", async () => {
  const seen: { url: string; init: RequestInit }[] = [];
  const bound = userApi(transport(200, load("account"), seen), { account: "u-0000000000000001" });
  await bound.account();
  await userApi(transport(201, load("quote"), seen), { account: "u-0000000000000001" }).quote("x");
  const sessions = userApi(transport(200, load("session-signed-in"), seen), { account: "u-0000000000000001" });
  await sessions.signOut();
  await sessions.session();
  await sessions.signIn("reader-a", "pw");
  const named = seen.map((sent) => (sent.init.headers as Record<string, string>)[ACCOUNT_HEADER] ?? null);
  assert.deepEqual(seen.map((sent) => sent.url), ["/api/user/account", "/api/user/analyses/x/quotes",
    "/api/session/logout", "/api/session", "/api/session/login"]);
  assert.deepEqual(named, ["u-0000000000000001", "u-0000000000000001", "u-0000000000000001", null, null]);
  await userApi(transport(201, load("quote"), seen)).quote("x");  // Unbound: the server refuses its writes.
  assert.equal((seen.at(-1)!.init.headers as Record<string, string>)[ACCOUNT_HEADER], undefined);
});

test("binding refusals are read and named; nothing else is one", async () => {
  const errors = load<Record<string, unknown>>("errors");
  const changed = await userApi(transport(401, errors.account_changed, []), { account: "u-0000000000000001" })
    .addSource({ headline: "h", source_url: "https://example.org/x", published_at: "2026-10-12T10:00:00+03:00",
                 source_text: "t" });
  assert.equal(changed.state, "refused");
  assert.equal(bindingRefusal(changed), "account_changed");
  const unbound = await userApi(transport(428, errors.account_binding_required, [])).quote("x");
  assert.equal(unbound.state, "refused");
  assert.equal(bindingRefusal(unbound), "account_binding_required");
  assert.equal(bindingRefusal(await userApi(transport(409, errors.daily_limit_reached, [])).quote("x")), null);
  assert.equal(bindingRefusal(await userApi(transport(200, load("account"), [])).account()), null);
  assert.equal(USER_CONTRACT, "user-api-0.5");
});

test("refusals, server errors, lost and unreadable replies are told apart, and nothing is retried", async () => {
  const errors = load<Record<string, unknown>>("errors");
  const seen: { url: string; init: RequestInit }[] = [];
  const refused = await userApi(transport(409, errors.daily_limit_reached, seen)).run("x", {
    quote_id: "q-12345678", effort: "high", credits: 6, approve: true });
  assert.equal(refused.state, "refused");
  assert.equal(refused.state === "refused" && refused.error.code, "daily_limit_reached");
  const failed = await userApi(transport(500, errors.internal_error, seen)).analysis("x");
  assert.equal(failed.state, "unconfirmed");
  const unreadable = await userApi(transport(200, { contract: USER_CONTRACT }, seen)).analysis("x");
  assert.equal(unreadable.state, "unconfirmed");
  const notJson = await userApi(transport(403, undefined, seen)).analyses();
  assert.equal(notJson.state, "unconfirmed");
  const lost = await userApi(async () => { throw new TypeError("network"); }).analyses();
  assert.equal(lost.state, "unconfirmed");
  assert.equal(seen.length, 4);
});
