// My analyses: the fail-closed reading of the library, honest review labels, search and filters kept in the address,
// and the way back from the review screen.
import assert from "node:assert/strict";
import test from "node:test";
import {
  ANALYSES_VIEW_VERSION, REVIEW_INFO, analysesHref, entryProblem, excerpt, facetCounts, filterAnalyses, modeDetail,
  noteExcerpt, publicationTimes, readAnalyses, readAnalysesFilters, returnPath, reviewDetail, reviewHref, reviewKey,
  sourceLink,
  type AnalysisEntry, type AnalysesFilters, type ReviewState,
} from "../src/analyses.ts";
import { fetchAnalyses } from "../src/api.ts";
import { matchRoute } from "../src/routes.ts";

const id = (digit: string) => digit.repeat(64);
const NONE: AnalysesFilters = { query: "", outcome: null, mode: null, review: null };

function entry(overrides: Partial<AnalysisEntry> = {}): AnalysisEntry {
  return {
    draft_id: id("a"), capture_id: "20261008T090000000000Z-aaaaaaaaaaaa", draft_view_sha256: id("f"),
    event: { headline: "Synthetic committee holds its rate", source_url: "https://example.com/statement",
             published_at: "2026-09-15T18:00:00Z", published_at_as_supplied: "2026-09-15T14:00:00-04:00" },
    captured_at: "2026-10-08T09:00:00+00:00", outcome: "draft", recorded_outcome: "draft", mode: "mock",
    provenance: { model: "claude-sonnet-5-5", effort: "medium", prompt_version: "draft-prompt-0.4",
                  sent_at: "2026-10-08T09:00:01+00:00", received_at: "2026-10-08T09:00:01+00:00", http_status: null,
                  request_id: null },
    model_output: { kind: "summary", text: "Mock workflow draft for the recorded event." },
    review: { state: "none", versions: 0 },
    ...overrides,
  };
}

const reply = (entries: unknown[], damaged: unknown[] = []) => ({
  view_version: ANALYSES_VIEW_VERSION, provider_called: false, entries, damaged,
  not_listed: { saved_events: { none: 1, incomplete: 0, awaiting_publication: 0 }, prepared_drafts: 2 },
});

const current = (status: "human_reviewed" | "needs_revision" | null, notes = "Checked the source."): ReviewState => ({
  state: "current", versions: 2, status, latest_saved_at: "2026-10-08T10:00:00+00:00", notes_excerpt: notes,
  notes_truncated: false, corrected_fields: 1,
});

test("the library route has one address, with or without a trailing slash", () => {
  assert.deepEqual(matchRoute("/analyses"), { page: "analyses" });
  assert.deepEqual(matchRoute("/analyses/"), { page: "analyses" });
});

test("a verified reply is read whole; an envelope from another version is refused", () => {
  const read = readAnalyses(reply([entry()]));
  assert.ok("library" in read);
  assert.equal(read.library.entries.length, 1);
  assert.deepEqual(read.library.not_listed.saved_events, { none: 1, incomplete: 0, awaiting_publication: 0 });
  for (const broken of [{ ...reply([]), view_version: "analysis-library-view-9" }, { ...reply([]), provider_called: true },
                        { ...reply([]), entries: null }, null]) {
    assert.ok("problem" in readAnalyses(broken));
  }
});

test("an entry this page cannot read is listed as unreadable with its reason, never dropped or shown as unreviewed", () => {
  const cases: [unknown, string][] = [
    [{ ...entry(), review: { state: "current", versions: 1 } }, "its current review is incomplete"],
    [{ ...entry(), review: { state: "maybe" } }, "its review state is not recognised"],
    [{ ...entry(), outcome: "partial" }, "its outcome is not recognised"],
    [{ ...entry(), mode: "free" }, "its response mode is not recognised"],
    [entry({ provenance: { ...entry().provenance, http_status: 200 } }), "labelled a local mock but records a provider reply"],
    [entry({ model_output: { kind: "problem", text: "x" } }), "its model output does not match its outcome"],
    [{ ...entry(), event: { headline: "" } }, "its event is incomplete"],
  ];
  for (const [item, reason] of cases) {
    const read = readAnalyses(reply([entry({ draft_id: id("b") }), item]));
    assert.ok("library" in read);
    assert.deepEqual(read.library.entries.map((row) => row.draft_id), [id("b")]);
    assert.equal(read.library.damaged.length, 1);
    assert.match(read.library.damaged[0].problem, new RegExp(reason));
  }
  const twice = readAnalyses(reply([entry(), entry()]));
  assert.ok("library" in twice);
  assert.equal(twice.library.entries.length, 1);
  assert.match(twice.library.damaged[0].problem, /listed twice/);
  const reported = readAnalyses(reply([], [{ capture_id: "c-1", draft_id: null, problem: "The view does not verify" }, {}]));
  assert.ok("library" in reported);
  assert.deepEqual(reported.library.damaged.map((row) => row.problem),
                   ["The view does not verify", "The server reported an unreadable record without a reason."]);
});

test("review labels restate their exact condition: only a current-view version counts as reviewed", () => {
  const labels = (review: ReviewState) => REVIEW_INFO[reviewKey(review)].label;
  assert.equal(labels({ state: "none", versions: 0 }), "Not reviewed");
  assert.equal(labels(current("human_reviewed")), "Human-reviewed");
  assert.equal(labels(current("needs_revision")), "Needs revision");
  assert.equal(labels(current(null)), "Notes, no status");
  const stale: ReviewState = { state: "stale", versions: 3, latest_saved_at: "2026-10-08T10:00:00+00:00" };
  assert.equal(labels(stale), "Not reviewed for this view");
  assert.match(reviewDetail(stale), /saved against an earlier version of this view, so it does not count/);
  const invalid: ReviewState = { state: "invalid", versions: null, problem: "unexpected file 000009.json" };
  assert.equal(labels(invalid), "Review history unreadable");
  assert.match(reviewDetail(invalid), /do not verify, so no review status is shown: unexpected file/);
  assert.match(reviewDetail(current("human_reviewed")), /marked reviewed by a person.*against the view shown now/);
  assert.equal(entryProblem(entry({ review: stale })), null);
});

test("response modes are labelled from the recorded mode and provenance", () => {
  assert.match(modeDetail(entry()), /Generated locally from a fixture shaped as claude-sonnet-5-5.*no provider was contacted/);
  const paid = entry({ mode: "paid", provenance: { ...entry().provenance, http_status: 529, request_id: "req_x" } });
  assert.equal(modeDetail(paid), "One approved paid request to claude-sonnet-5-5 (draft-prompt-0.4), HTTP 529.");
});

test("publication times keep the recorded offset and show the same instant in UTC, never the reader's zone", () => {
  assert.deepEqual(publicationTimes(entry()), { local: "15 Sep 2026, 14:00 UTC−04:00", utc: "15 Sep 2026, 18:00 UTC" });
  const unknown = entry({ event: { ...entry().event, published_at_as_supplied: "2026-09-15T18:00:00Z" } });
  assert.deepEqual(publicationTimes(unknown), { local: null, utc: "15 Sep 2026, 18:00 UTC" });
});

test("search covers the headline, source, model output and the latest current note; filters combine", () => {
  const rows = [
    entry({ draft_id: id("1") }),
    entry({ draft_id: id("2"), outcome: "no_draft", model_output: { kind: "explanation", text: "No hypothesis here." },
            mode: "paid", provenance: { ...entry().provenance, http_status: 200, request_id: "r" },
            review: current("human_reviewed", "Agreed with the refusal") }),
    entry({ draft_id: id("3"), outcome: "technical_failure", model_output: { kind: "problem", text: "HTTP 529" },
            mode: "paid", provenance: { ...entry().provenance, http_status: 529, request_id: "r2" },
            review: { state: "stale", versions: 1, latest_saved_at: "2026-10-08T10:00:00+00:00" } }),
  ];
  const ids = (filters: Partial<AnalysesFilters>) => filterAnalyses(rows, { ...NONE, ...filters }).map((row) => row.draft_id);
  assert.deepEqual(ids({ query: "REFUSAL agreed" }), [id("2")]);
  assert.deepEqual(ids({ query: "example.com" }), [id("1"), id("2"), id("3")]);
  assert.deepEqual(ids({ query: "529" }), [id("3")]);
  assert.deepEqual(ids({ mode: "paid" }), [id("2"), id("3")]);
  assert.deepEqual(ids({ mode: "paid", outcome: "technical_failure" }), [id("3")]);
  assert.deepEqual(ids({ review: "human_reviewed" }), [id("2")]);
  assert.deepEqual(ids({ review: "stale" }), [id("3")]);
  assert.deepEqual(ids({ review: "none" }), [id("1")]);  // A stale review never counts as "not reviewed" here either.
  assert.deepEqual(facetCounts(rows, { ...NONE, mode: "paid" }, "outcome"), { all: 2, no_draft: 1, technical_failure: 1 });
  assert.deepEqual(facetCounts(rows, { ...NONE, mode: "paid" }, "mode"), { all: 3, mock: 1, paid: 2 });
});

test("the browsing state round-trips through the address; unknown values are no filter, never a guess", () => {
  const filters: AnalysesFilters = { query: "jobs report", outcome: "no_draft", mode: "paid", review: "needs_revision" };
  const href = analysesHref(filters);
  assert.equal(href, "/analyses?q=jobs+report&outcome=no_draft&mode=paid&review=needs_revision");
  assert.deepEqual(readAnalysesFilters(href.slice("/analyses".length)), filters);
  assert.equal(analysesHref(NONE), "/analyses");
  const odd = readAnalysesFilters("?outcome=great&mode=cheap&review=done&q=%E0%A4%A");  // Malformed escapes never throw.
  assert.deepEqual({ ...odd, query: typeof odd.query }, { query: "string", outcome: null, mode: null, review: null });
});

test("the review link reuses the Tracker's deep link and carries only a way back to this page", () => {
  const href = reviewHref(entry(), { ...NONE, review: "none" });
  assert.equal(href, `/?draft=${id("a")}&from=${encodeURIComponent("/analyses?review=none")}`);
  assert.equal(returnPath(href.slice(1)), "/analyses?review=none");
  assert.equal(returnPath("?draft=x&from=%2Fanalyses"), "/analyses");
  for (const hostile of ["//evil.example/analyses", "https://evil.example", "/analysesX", "/analyses#top", "/", ""]) {
    assert.equal(returnPath(`?from=${encodeURIComponent(hostile)}`), null, hostile);
  }
  assert.equal(returnPath("?draft=x"), null);
});

test("previews are short, and only http(s) sources become links", () => {
  const long = `${"word ".repeat(80)}end`;
  const cut = excerpt(long, 50) as string;
  assert.ok(cut.length <= 51 && cut.endsWith("…"));
  assert.equal(excerpt(null), null);
  assert.equal(noteExcerpt({ ...current(null, "Short note."), notes_truncated: true }), "Short note.…");
  assert.equal(noteExcerpt({ state: "none", versions: 0 }), null);
  assert.deepEqual(sourceLink("https://www.bls.gov/news.release/empsit.htm"),
                   { href: "https://www.bls.gov/news.release/empsit.htm", label: "www.bls.gov" });
  for (const unsafe of ["javascript:alert(1)", "data:text/html,x", "not a url", ""]) assert.equal(sourceLink(unsafe), null);
});

test("the client reads the library with one GET and reports a refusal or an unverified reply as an error", async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  const answer = (status: number, body: unknown) => (async (url: string, init?: RequestInit) => {
    sent.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  const original = globalThis.fetch;
  try {
    globalThis.fetch = answer(200, reply([entry()]));
    const ready = await fetchAnalyses(new AbortController().signal);
    assert.equal(ready.state, "ready");
    assert.equal(sent[0].url, "/api/analyses");
    assert.equal(sent[0].init?.method ?? "GET", "GET");
    globalThis.fetch = answer(500, { detail: "The saved analyses could not be read (PermissionError)" });
    assert.deepEqual(await fetchAnalyses(new AbortController().signal),
                     { state: "error", message: "The saved analyses could not be read (PermissionError)" });
    globalThis.fetch = answer(200, { view_version: "something-else" });
    const unverified = await fetchAnalyses(new AbortController().signal);
    assert.equal(unverified.state, "error");
  } finally {
    globalThis.fetch = original;
  }
});
