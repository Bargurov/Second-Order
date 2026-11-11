// What the Client says, built from the SYNTHETIC user-contract fixtures: allowance and reset times in the server's
// quota time zone, charges, history, refusals with their next steps, evidence locators and marking, addresses, review
// drafts. Every sentence produced here is also checked for vocabulary that belongs to the administrator's view only.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  ERROR_CODES, MAX_NOTES, MAX_SOURCE_URL_CHARACTERS, codePoints, type Account, type Analysis, type AnalysisSummary, type ApiError, type Quote,
} from "../src/contracts/user.ts";
import { locator, markedSource } from "../src/client/evidence.ts";
import { href, matchClientPath } from "../src/client/paths.ts";
import {
  ATTEMPT_LINE, HEADLINE_NOTE, OUTCOME_LABEL, RUNNING_NOTE, SOURCE_SIZE_NOTE, SOURCE_URL_NOTE, STATE_LABEL, UNCERTAIN_NOTE,
  approvalSentence, chargeLine, entitlements, historyRows, missingSteps, quoteTimes, sourceFormProblems,
} from "../src/client/present.ts";
import { NEXT_TEXT, noticeFor, sessionEndedBy } from "../src/client/refusals.ts";
import { draftProblems, isDirty, reviewForm, startingDraft } from "../src/client/reviewDraft.ts";
import { dayLabel, inUtc, inZone } from "../src/client/time.ts";

const load = <T>(name: string): T =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const account = load<Account>("user-contract-account");
const unavailable = load<Account>("user-contract-account-unavailable");
const readerB = load<Account>("client-account-reader-b");
const errors = load<Record<string, ApiError>>("user-contract-errors");
const quote = load<{ quote: Quote }>("user-contract-quote").quote;
const recorded = load<{ analysis: Analysis }>("user-contract-analysis-recorded").analysis;
const prepared = load<{ analysis: Analysis }>("user-contract-analysis-prepared").analysis;
const analyses = load<{ analyses: AnalysisSummary[] }>("user-contract-analyses").analyses;
/** Vocabulary of the administrator's view: product and vendor names, money, usage figures, internal transport terms. */
const ADMIN_ONLY = /claude|sonnet|opus|haiku|anthropic|openai|\$\s?\d|\busd\b|dollar|\btokens?\b|\bcosts?\b|\bprovider\b|\bmodel\b|http status|request id/i;
const said: string[] = [];
const say = <T>(value: T): T => {
  said.push(JSON.stringify(value));
  return value;
};

test("times are shown in the server's quota time zone, across daylight-saving changes, and in UTC", () => {
  assert.equal(inZone("2026-10-14T21:00:00+00:00", "Asia/Jerusalem"), "15 Oct 2026, 00:00 (Asia/Jerusalem)");
  assert.equal(inZone("2026-12-14T22:00:00+00:00", "Asia/Jerusalem"), "15 Dec 2026, 00:00 (Asia/Jerusalem)");
  assert.equal(inUtc("2026-10-14T21:00:00+00:00"), "14 Oct 2026, 21:00 UTC");
  assert.equal(inZone("2026-10-14T21:00:00+00:00", "Not/AZone"), "14 Oct 2026, 21:00 UTC");
  assert.equal(dayLabel("2026-10-14"), "14 Oct 2026");
});

test("the allowance repeats the server's figures and says the server checks again", () => {
  const lines = say(entitlements(account, "2026-10-14T09:00:00+00:00"));
  assert.equal(lines.credits, "40 credits available");
  assert.equal(lines.held, null);
  assert.equal(lines.daily, "3 of 3 analyses left today (0 used on 14 Oct 2026)");
  assert.equal(lines.reset, "15 Oct 2026, 00:00 (Asia/Jerusalem)");
  assert.equal(lines.resetUtc, "14 Oct 2026, 21:00 UTC");
  assert.equal(lines.availability, null);
  assert.match(lines.basis, /server checks your balance and allowance again/);
  const b = say(entitlements(readerB, "2026-10-14T09:00:00+00:00"));
  assert.equal(b.daily, "0 of 2 analyses left today (2 used on 14 Oct 2026)");
  assert.match(b.held!, /^4 credits held by analyses/);
  const none = say(entitlements(unavailable, "2026-10-14T09:00:00+00:00"));
  assert.equal(none.daily, "No daily analysis limit is set for your account");
  assert.equal(none.availability, unavailable.analysis.detail);
});

test("before a first analysis, every missing step the server lists, in its order and in its own words", () => {
  assert.deepEqual(missingSteps(account), []);
  const unallocated = load<Account>("user-contract-account-unallocated");
  assert.deepEqual(say(missingSteps(unallocated)).map((step) => [step.reason, step.detail]),
                   [["no_credits_allocated", unallocated.analysis.detail]]);
  // A newly approved account, as the server reports it: both of the administrator's steps, in the server's order.
  const steps = unallocated.analysis.reasons!;
  const approved = { ...unallocated, daily: { ...unallocated.daily, limit: null, remaining: null },
    analysis: { available: false as const, reason: "no_daily_limit" as const, detail: unavailable.analysis.detail!,
                reasons: [{ reason: "no_daily_limit" as const, detail: unavailable.analysis.detail! }, ...steps] } };
  const both = say(missingSteps(approved));
  assert.deepEqual(both.map((step) => step.reason), ["no_daily_limit", "no_credits_allocated"]);
  assert.deepEqual(both.map((step) => step.title), ["No daily allowance is set for your account",
                                                    "No credits have been allocated to your account"]);
  assert.ok(both.every((step) => /administrator/.test(step.who)));
  // A user-api-0.1 account names one reason only, and is still read.
  const { reasons: _listed, ...older } = unavailable.analysis;
  assert.deepEqual(missingSteps({ ...unavailable, analysis: older as Account["analysis"] }).map((step) => step.reason),
                   ["no_daily_limit"]);
  const spent = { ...readerB, credits: { available: 0, held: 4 }, analysis: { available: false as const,
    reason: "no_credits_available" as const, detail: "No credits are available now. Ask the administrator.",
    reasons: [{ reason: "no_credits_available" as const, detail: "No credits are available now. Ask the administrator." }] } };
  assert.match(say(missingSteps(spent))[0].held!, /^4 credits held by analyses/);
  for (const reason of ["sending_disabled", "no_credit_policy", "no_effort_enabled"] as const) {
    const server = missingSteps({ ...account, analysis: { available: false, reason, detail: "SYNTHETIC detail" } });
    assert.match(say(server)[0].who, /whole server/, reason);
  }
});

test("the source form states the server's limits: 50,000 characters in any script, a headline of 1,500 on one line", () => {
  assert.match(say(SOURCE_SIZE_NOTE), /50,000 characters in any script/);
  assert.doesNotMatch(SOURCE_SIZE_NOTE, /refused|before 50,000|four times/);
  assert.match(say(HEADLINE_NOTE), /one line, up to 1,500 characters/);
  assert.deepEqual(sourceFormProblems({ headline: "A headline", text: "Some text." }), {});
  // Characters are code points, as the server counts them: four-byte characters fit to the same counts.
  assert.deepEqual(sourceFormProblems({ headline: "😀".repeat(1_500), text: "😀".repeat(50_000) }), {});
  assert.match(say(sourceFormProblems({ headline: "😀".repeat(1_501), text: "" })).headline!, /1,501 of 1,500/);
  assert.match(sourceFormProblems({ headline: "A", text: "a".repeat(50_001) }).text!, /50,001 of 50,000/);
  assert.match(sourceFormProblems({ headline: "Line one\nline two", text: "a" }).headline!, /one line/);
});

test("the source address is an http(s) address of at most 2,083 UTF-8 bytes as sent, said before saving", () => {
  assert.equal(MAX_SOURCE_URL_CHARACTERS, 2_083);  // The shared constant, held equal to the server's.
  assert.match(say(SOURCE_URL_NOTE), /web address beginning with https:\/\/ or http:\/\/, at most 2,083 characters, where a character outside basic Latin counts as two to four/);
  const address = (source_url: string) => say(sourceFormProblems({ headline: "A", text: "a", source_url })).source_url;
  const base = "https://example.com/";  // 20 bytes.
  const exactly = `${base}${"a".repeat(2_083 - 20)}`;
  const accentedAtLimit = `${base}${"é".repeat(1_031)}a`;  // 20 + 2 × 1,031 + 1 = 2,083 bytes, 1,052 characters.
  for (const accepted of ["", "  ", "https://example.com/a?b=c#d", "http://example.com", "  https://example.com/x  ",
                          "https://例え.jp/記事", exactly, `  ${exactly}  `, accentedAtLimit]) {
    assert.equal(address(accepted), undefined, accepted.slice(0, 40));
  }
  // Counted as the server counts: UTF-8 bytes of the address as sent, so 1,052 characters of which 1,032 are accented
  // are over the limit.
  assert.match(address(`${exactly}a`)!, /^The address counts as 2,084 characters, where a character outside basic Latin counts as two to four; at most 2,083 are accepted\.$/);
  assert.match(address(`${base}${"é".repeat(1_032)}`)!, /counts as 2,084 characters/);
  assert.match(address(`${base}${"記".repeat(700)}`)!, /counts as 2,120 characters/);  // Three bytes each.
  for (const incomplete of ["example.com/a", "www.example.com", "https://", "https:// example.com"]) {
    assert.match(address(incomplete)!, /^Not a complete web address yet: it begins with https:\/\/ or http:\/\//, incomplete);
  }
  for (const other of ["ftp://example.com/file", "mailto:desk@example.com", "javascript:void(0)", "file:///C:/a.txt"]) {
    assert.match(address(other)!, /^Only a web address beginning with https:\/\/ or http:\/\/ is accepted/, other);
  }
  // A form without the address (as earlier callers pass it) reports nothing about it.
  assert.equal("source_url" in sourceFormProblems({ headline: "A", text: "a" }), false);
});

test("charges are stated as the server settled them, never more than reserved", () => {
  const charge = { credits_reserved: 6, quota_day: "2026-10-14" };
  assert.match(say(chargeLine({ ...charge, state: "held", credits_charged: null, credits_returned: null }))!,
               /^6 credits reserved while it runs/);
  assert.match(say(chargeLine({ ...charge, state: "under_review", credits_charged: null, credits_returned: null }))!,
               /held for an administrator's review.*Nothing is refunded or charged automatically/);
  assert.equal(say(chargeLine({ ...charge, state: "charged", credits_charged: 4, credits_returned: 2 })),
               "4 credits charged of 6 credits reserved; 2 returned, counted on 14 Oct 2026's allowance.");
  assert.match(say(chargeLine({ ...charge, state: "returned", credits_charged: 0, credits_returned: 6 }))!, /^6 credits returned/);
  assert.equal(chargeLine(null), null);
});

test("history is newest first; outcomes, reviews and credits appear only when the server has them", () => {
  const rows = say(historyRows(analyses, account));
  const times = analyses.map((row) => Date.parse(row.prepared_at)).sort((a, b) => b - a);
  assert.deepEqual(rows.map((row) => analyses.find((item) => item.analysis_id === row.analysisId)!.prepared_at)
    .map((time) => Date.parse(time)), times);
  for (const row of rows) {
    const source = analyses.find((item) => item.analysis_id === row.analysisId)!;
    assert.equal(row.state, STATE_LABEL[source.state]);
    assert.equal(row.outcome, source.outcome ? OUTCOME_LABEL[source.outcome] : null);
    assert.deepEqual([row.stateKey, row.outcomeKey], [source.state, source.outcome]);  // Styling follows the state.
    assert.equal(row.credits === null, source.credits_charged === null);
    assert.equal(row.review === null, source.state !== "recorded");
  }
});

test("the approval names the analysis, its Effort and the exact credits; the quote's validity is the server's", () => {
  const sentence = say(approvalSentence(prepared, quote, account));
  assert.match(sentence, /High Effort analysis of “Simulated statistics office publishes its quarterly survey”/);
  assert.match(sentence, /reserves 6 credits now and one of today's analyses; I am never charged more than 6 credits/);
  const times = say(quoteTimes(quote, "Asia/Jerusalem"));
  assert.equal(times.until, "14 Oct 2026, 12:50 (Asia/Jerusalem)");
  assert.equal(times.issued, "Issued 14 Oct 2026, 12:35 (Asia/Jerusalem), by the server's clock");
});

test("every error code has a notice; each next step is a deliberate action, never an automatic one", () => {
  const steps: Record<string, string> = {};
  for (const code of ERROR_CODES) {
    const notice = say(noticeFor({ state: "refused", status: 409, error: errors[code] }, quote, "Asia/Jerusalem"));
    assert.ok(notice.title.length > 0, code);
    assert.equal(notice.detail, errors[code].detail, code);
    steps[code] = notice.next;
  }
  assert.equal(steps.quote_expired, "new_quote");
  assert.equal(steps.quote_superseded, "new_quote");
  assert.equal(steps.unsupported_effort, "choose_effort");
  assert.equal(steps.result_changed, "read_again");
  assert.equal(steps.review_conflict, "read_again");
  const credits = noticeFor({ state: "refused", status: 409, error: errors.insufficient_credits }, quote);
  assert.match(credits.facts.join(" "), /needs 6 credits/);
  assert.match(credits.facts.join(" "), new RegExp(`${errors.insufficient_credits.credits!.available} credit`));
  const daily = noticeFor({ state: "refused", status: 409, error: errors.daily_limit_reached }, null, "Asia/Jerusalem");
  assert.match(daily.facts.join(" "), /resets .*\(Asia\/Jerusalem\) \(.* UTC\)/);
  assert.match(daily.facts.join(" "), /Nothing was reserved or charged/);
  const effort = noticeFor({ state: "refused", status: 409, error: errors.unsupported_effort });
  assert.deepEqual(effort.efforts, errors.unsupported_effort.efforts);
  for (const text of Object.values(NEXT_TEXT)) if (text) assert.doesNotMatch(text, /automatic|retrying|will retry/i);
});

test("an unconfirmed reply proves nothing and is never retried; a 401 ends the session", () => {
  const notice = say(noticeFor({ state: "unconfirmed", status: 503, message: "Unexpected reply (503).", error: null }));
  assert.deepEqual([notice.tone, notice.next], ["unconfirmed", "read_again"]);
  assert.match(notice.detail, /Nothing was retried/);
  const lost = noticeFor({ state: "unconfirmed", status: null, error: null,
    message: "No reply arrived from the server. Nothing was retried; read the page again before acting." });
  assert.equal(lost.detail.match(/Nothing was retried/g)?.length, 1);  // Said once, whoever said it first.
  assert.equal(sessionEndedBy({ state: "refused", status: 401, error: errors.session_expired }), "session_expired");
  assert.equal(sessionEndedBy({ state: "refused", status: 401, error: errors.not_signed_in }), "not_signed_in");
  assert.equal(sessionEndedBy({ state: "unconfirmed", status: 401, message: "x", error: null }), "not_signed_in");
  assert.equal(sessionEndedBy({ state: "refused", status: 409, error: errors.quote_expired }), null);
});

test("evidence: locators come from the server's offsets, and the marked text is the source text, unchanged", () => {
  const text = recorded.source.text;
  const content = recorded.result!.analysis!;
  const segments = markedSource(text, content);
  assert.equal(segments.map((segment) => segment.text).join(""), text);
  const characters = Array.from(text);
  let offset = 0;
  const marked = new Set<number>();
  for (const segment of segments) {
    const length = Array.from(segment.text).length;
    if (segment.statements.length) for (let index = offset; index < offset + length; index++) marked.add(index);
    offset += length;
  }
  for (const item of content.established) {
    for (const quoted of item.quotes) {
      assert.equal(codePoints(text, quoted.start, quoted.end), quoted.source_passage);
      for (let index = quoted.start; index < quoted.end; index++) assert.ok(marked.has(index));
      assert.match(say(locator(quoted)), new RegExp(`^Paragraphs? \\d+(–\\d+)?, characters ${quoted.start + 1}–${quoted.end}`));
    }
  }
  assert.equal(characters.length, offset);
  assert.deepEqual(markedSource("plain", null), [{ text: "plain", statements: [] }]);
});

test("evidence: a Go deeper quote's locator names the report, its publisher and the part quoted", () => {
  const quoted = recorded.result!.analysis!.established[0].quotes[0];
  const parts = { headline: "its headline", excerpt: "its feed excerpt", text: "its publication text" } as const;
  for (const [part, words] of Object.entries(parts)) {
    const shown = say(locator({ ...quoted, occurrences: 2,
      evidence: { report: 2, publisher: "Synthetic Ledger", part: part as keyof typeof parts } }));
    assert.match(shown, new RegExp(`Report 2, Synthetic Ledger, ${words}`));
    assert.match(shown, /occurs 2 times in the publishers' words/);
  }
  assert.doesNotMatch(locator(quoted), /Report \d/);  // An ordinary source's quote names no report.
});

test("addresses: known pages, opaque IDs, and a malformed address is Not Found", () => {
  // News is the home (docs/news-stories-contract.md section 7); Your analyses moved from / to /analyses.
  assert.deepEqual(matchClientPath("/"), { view: "news", tab: "hot" });
  assert.deepEqual(matchClientPath("/client.html"), { view: "news", tab: "hot" });
  assert.deepEqual(matchClientPath(href.news), { view: "news", tab: "hot" });
  for (const tab of ["hot", "coverage", "latest", "topics", "interests"] as const) {
    assert.deepEqual(matchClientPath(href.newsTab(tab)), { view: "news", tab });
  }
  assert.deepEqual(matchClientPath(href.analyses), { view: "analyses" });
  assert.deepEqual(matchClientPath(href.reports), { view: "reports" });
  assert.deepEqual(matchClientPath(href.story("story-0123456789abcdef")), { view: "story", storyId: "story-0123456789abcdef" });
  assert.deepEqual(matchClientPath(href.deeper("story-0123456789abcdef")), { view: "deeper", storyId: "story-0123456789abcdef" });
  assert.deepEqual(matchClientPath(href.topic("topic-0123456789abcdef")), { view: "topic", topicId: "topic-0123456789abcdef" });
  assert.deepEqual(matchClientPath(href.newsImport("imp-0123456789abcdef")), { view: "import", importId: "imp-0123456789abcdef" });
  assert.deepEqual(matchClientPath("/sources/"), { view: "sources" });
  assert.deepEqual(matchClientPath("/sources/new"), { view: "new-source" });
  assert.deepEqual(matchClientPath(href.analysis(prepared.analysis_id)), { view: "analysis", analysisId: prepared.analysis_id });
  assert.deepEqual(matchClientPath(href.source("a b")), { view: "source", sourceId: "a b" });
  assert.deepEqual(matchClientPath("/credits"), { view: "credits" });
  assert.deepEqual(matchClientPath("/register"), { view: "signed-in" });
  assert.deepEqual(matchClientPath("/sign-in/"), { view: "signed-in" });
  for (const bad of ["/analyses/%E0%A4%A", "/analyses/a%2Fb", "/admin", "/analyses/x/runs", "/h/1", "/news/stories",
                     "/news/stories/a%2Fb", "/news/stories/x/deeper/y", "/news/topics/%E0%A4%A", "/news/popular"]) {
    assert.deepEqual(matchClientPath(bad), { view: "not-found" }, bad);
  }
});

test("a review draft starts from the latest version for this result and is saved only when it changed", () => {
  const start = startingDraft(recorded);
  const latest = recorded.reviews.at(-1)!;
  assert.deepEqual(start, { status: latest.status, notes: latest.notes });
  assert.equal(isDirty(recorded, start), false);
  assert.ok(draftProblems(recorded, start).includes("Nothing changed since the last saved version."));
  const edited = { ...start, notes: `${start.notes} Checked again.` };
  assert.deepEqual(draftProblems(recorded, edited), []);
  assert.deepEqual(reviewForm(recorded, edited), { parent_review_id: latest.review_id,
    result_sha256: recorded.result_sha256, status: edited.status, notes: edited.notes });
  assert.ok(draftProblems(recorded, { status: null, notes: "  " }).includes("Choose a status or write a note."));
  assert.ok(draftProblems(recorded, { status: null, notes: "x".repeat(MAX_NOTES + 1) }).length > 0);
  assert.deepEqual(draftProblems(prepared, { status: "human_reviewed", notes: "" }), ["There is no recorded result to review."]);
  const elsewhere = { ...recorded, result_sha256: "f".repeat(64) };
  assert.deepEqual(startingDraft(elsewhere), { status: null, notes: "" });  // An older result's review is not this one's.
});

test("credit wording follows the server's charge state, before and after an administrator's reconciliation", () => {
  const credits = (count: number) => `${count} ${count === 1 ? "credit" : "credits"}`;
  for (const kind of ["failed", "unresolved"] as const) {
    const before = load<{ analysis: Analysis }>(`user-contract-analysis-${kind}`).analysis;
    const reserved = before.charge!.credits_reserved;
    const unsettled = say(chargeLine(before.charge))!;
    assert.match(unsettled, new RegExp(`^${credits(reserved)} held for an administrator's review`), kind);
    assert.doesNotMatch(unsettled, /charged of|returned/, `${kind}: unknown amounts stay unstated`);
    const expected: Record<string, string> = {
      charged: `${credits(reserved)} charged of ${credits(reserved)} reserved, counted on 14 Oct 2026's allowance.`,
      partial: `${credits(Math.floor(reserved / 2))} charged of ${credits(reserved)} reserved; ` +
               `${reserved - Math.floor(reserved / 2)} returned, counted on 14 Oct 2026's allowance.`,
      zero: `0 credits charged of ${credits(reserved)} reserved; ${reserved} returned, counted on 14 Oct 2026's allowance.`,
      returned: `${credits(reserved)} returned; nothing was charged.`,
    };
    for (const [variant, line] of Object.entries(expected)) {
      const after = load<{ analysis: Analysis }>(`client-analysis-${kind}-${variant}`).analysis;
      assert.equal(after.state, kind);
      assert.equal(say(chargeLine(after.charge)), line, `${kind}-${variant}`);
      // The attempt's own words never speak for its credits: nothing says they are still held once settled.
      const page = [STATE_LABEL[after.state], ATTEMPT_LINE[after.state]!, chargeLine(after.charge)!].join(" ");
      assert.doesNotMatch(page, /\bheld\b|reserved until/i, `${kind}-${variant}`);
      assert.match(ATTEMPT_LINE[after.state]!, /not (run|sent) again/, `${kind}-${variant} stays non-retryable`);
    }
  }
  for (const label of Object.values(STATE_LABEL)) assert.doesNotMatch(label, /credit|held|charged|returned/i);
});

test("the running note promises one attempt, not a recorded outcome; the uncertain note offers only a read", () => {
  assert.match(say(RUNNING_NOTE), /sent once and never again/);
  assert.match(RUNNING_NOTE, /come back and read this page again to see what the server has recorded/);
  assert.match(RUNNING_NOTE, /if no outcome could be recorded, the attempt is held for an administrator's review/);
  assert.doesNotMatch(RUNNING_NOTE, /either way|will be recorded|is recorded|does not stop/i);
  assert.match(say(UNCERTAIN_NOTE), /does not know whether it was sent/);
  assert.match(UNCERTAIN_NOTE, /until the analysis is read again from the server/);
  for (const line of Object.values(ATTEMPT_LINE)) say(line);
});

test("nothing the Client says carries the administrator's vocabulary", () => {
  assert.ok(said.length > 20);
  for (const text of said) assert.doesNotMatch(text, ADMIN_ONLY, text);
});
