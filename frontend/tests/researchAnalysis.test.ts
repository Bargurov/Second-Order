// Evidence-first research analysis, against replies the backend serves (captured by tests/test_research_analysis.py
// into fixtures/research-analysis-*.json from SYNTHETIC captures and replies): a prepared request with nothing sent,
// mock results (an analysis with a review, no additional finding, a decline), a paid analysis whose quotes were found
// exactly and after normalizing typography, and a paid reply refused because a quote was not in the source. Replies
// are read fail-closed: a quote must sit at its recorded place in the captured text the request carries, the outcome
// must agree with what the result carries, and the interpretation may name only statements that exist.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { historyStatement, type ProcessingHistory } from "../src/eventOverview.ts";
import { matchRoute } from "../src/routes.ts";
import {
  BASIS_LABEL, OUTCOME_LABEL, capturedText, codePoints, fetchResearch, latestReview, locator, markedSource,
  prepareResearch, readListing, readResearch, researchHref, reviewPayload, reviewProblems, sendMock, sendPaid,
  type ResearchRequestView,
} from "../src/researchAnalysis.ts";

const fixture = <T>(name: string): T => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const prepared = fixture<ResearchRequestView>("research-analysis-prepared.json");
const reviewed = fixture<ResearchRequestView>("research-analysis-reviewed.json");
const noFinding = fixture<ResearchRequestView>("research-analysis-no-finding.json");
const declined = fixture<ResearchRequestView>("research-analysis-declined.json");
const paid = fixture<ResearchRequestView>("research-analysis-paid.json");
const invalid = fixture<ResearchRequestView>("research-analysis-invalid.json");
const listing = fixture<Record<string, unknown>>("research-analysis-list.json");
const copy = <T>(value: T): T => structuredClone(value);
const problem = (body: unknown) => {
  const read = readResearch(body);
  return "problem" in read ? read.problem : null;
};

async function withFetch<T>(status: number, body: unknown, run: () => Promise<T>,
                            seen: { url: string; init?: RequestInit }[] = []): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    seen.push({ url, init });
    return new Response(JSON.stringify(body), { status });
  }) as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

test("every served research payload verifies as served", () => {
  for (const view of [prepared, reviewed, noFinding, declined, paid, invalid]) {
    assert.equal(problem(view), null, view.request_id);
  }
  assert.ok("listing" in readListing(listing, reviewed.capture_id));
  assert.ok("problem" in readListing(listing, prepared.capture_id));  // Another capture's list is refused.
});

test("a prepared request is shown as prepared and unsent, never as an analysis", () => {
  assert.equal(prepared.status, "Prepared · Nothing sent");
  assert.equal(prepared.attempt.state, "none");
  assert.equal(prepared.result, null);
  assert.match(prepared.not_an_analysis, /A prepared request is not an analysis/);
  assert.equal(prepared.origin.state, "verified");
  assert.equal(prepared.baseline.state, "not_supplied");
  for (const claimed of [{ ...copy(prepared), result_view_sha256: "0".repeat(64) },
                         { ...copy(prepared), attempt: { ...prepared.attempt, state: "recorded" } },
                         { ...copy(prepared), result: copy(paid.result) }]) {
    assert.match(problem(claimed) ?? "", /attempt state and the result disagree|another request/);
  }
});

test("each quote is found again at its recorded place in the captured text the request carries", () => {
  const source = capturedText(paid.request)!;
  assert.match(source, /^September 16, 2026\n\n/);
  const [exact, normalized] = paid.result!.analysis!.established[0].quotes;
  assert.equal(codePoints(source, exact.start, exact.end), exact.text);
  assert.equal(normalized.match, "normalized");
  assert.equal(normalized.source_passage, "in support of the Committee’s goals");
  assert.notEqual(normalized.text, normalized.source_passage);
  assert.equal(locator(exact), "Paragraph 3, characters 72–129 · exact match");
  assert.match(locator(normalized), /^Paragraph 3, characters 131–166 · matched after making quotation marks/);

  const moved = copy(paid);
  moved.result!.analysis!.established[0].quotes[0].start += 1;
  assert.match(problem(moved) ?? "", /not at its recorded place/);
  const reworded = copy(paid);
  reworded.result!.analysis!.established[1].quotes[0].source_passage = "Economic activity is contracting.";
  assert.match(problem(reworded) ?? "", /not at its recorded place/);
  const otherSource = copy(paid);
  const message = (otherSource.request.messages as { content: string }[])[0];
  message.content = message.content.replace("solid pace", "slower pace");
  assert.match(problem(otherSource) ?? "", /not at its recorded place/);
});

test("the outcome must agree with what the result carries, and the interpretation with its statements", () => {
  const relabelled = copy(paid);
  relabelled.result!.outcome = "no_additional_finding";
  assert.match(problem(relabelled) ?? "", /interpretation does not agree/);
  const outOfRange = copy(paid);
  outOfRange.result!.analysis!.interpretation.based_on = [1, 4];
  assert.match(problem(outOfRange) ?? "", /names statements that do not exist/);
  const unnumbered = copy(paid);
  unnumbered.result!.analysis!.established[1].number = 3;
  assert.match(problem(unnumbered) ?? "", /not numbered in order/);
  const smuggled = copy(invalid);
  smuggled.result!.analysis = copy(paid.result!.analysis);
  assert.match(problem(smuggled) ?? "", /does not agree with what it carries/);
  const frozen = copy(paid) as unknown as { result: { frozen: boolean } };
  frozen.result.frozen = true;
  assert.match(problem(frozen) ?? "", /could not be verified/);
  const elsewhere = copy(paid);
  elsewhere.result!.provenance.request_sha256 = "0".repeat(64);
  assert.match(problem(elsewhere) ?? "", /another request/);
  assert.match(problem({ ...copy(paid), provider_called: true }) ?? "", /could not be verified/);
});

test("results that carry no analysis say why, and mocks are labelled synthetic", () => {
  assert.equal(invalid.result!.outcome, "invalid");
  assert.equal(invalid.result!.analysis, null);
  assert.match(invalid.result!.problem!, /was not found in the captured text/);
  assert.equal(declined.result!.outcome, "declined");
  assert.match(declined.result!.model_text!, /Mock refusal/);  // research-prompt-2: a decline is a refusal.
  assert.equal(noFinding.result!.analysis!.interpretation.kind, "no_additional_finding");
  assert.equal(OUTCOME_LABEL[noFinding.result!.outcome], "No additional finding");
  for (const view of [reviewed, noFinding, declined]) {
    assert.equal(view.result!.mode, "mock");
    assert.equal(view.result!.synthetic, true);
  }
  assert.equal(paid.result!.synthetic, false);
  assert.match(BASIS_LABEL.forecast, /attributed, not an outcome/);
});

test("the captured text is marked where it is quoted, and nothing else changes", () => {
  const source = capturedText(paid.request)!;
  const pieces = markedSource(source, paid.result!.analysis);
  assert.equal(pieces.map((piece) => piece.text).join(""), source);
  const marked = pieces.filter((piece) => piece.statements.length > 0);
  assert.deepEqual(marked.map((piece) => [piece.text, piece.statements]), [
    ["decided to raise the target range by 1/4 percentage point", [1]],
    ["in support of the Committee’s goals", [1]],
    ["Economic activity is expanding at a solid pace.", [2]],
    ["will support a timelier return to the 2 percent goal", [3]],
  ]);
  assert.deepEqual(markedSource(source, null), [{ text: source, statements: [] }]);
});

test("a review version follows the latest one and is bound to the result shown", () => {
  const latest = latestReview(reviewed)!;
  assert.equal(latest.binding.result_view_sha256, reviewed.result_view_sha256);
  const payload = reviewPayload(reviewed, "human_reviewed", "Checked.");
  assert.deepEqual(payload, {
    parent_review_id: latest.review_id, status: "human_reviewed", notes: "Checked.",
    binding: { result_view_sha256: reviewed.result_view_sha256, request_sha256: reviewed.request_sha256,
               response_sha256: reviewed.result!.provenance.response_sha256 } });
  assert.deepEqual(reviewProblems(reviewed, latest.status, latest.notes), ["Nothing changed since the last saved version."]);
  assert.deepEqual(reviewProblems(reviewed, null, "  "), ["Add notes or choose a status."]);
  const broken = copy(reviewed);
  broken.reviews.records[0].parent_review_id = "0".repeat(64);
  assert.match(problem(broken) ?? "", /does not follow the one before it/);
});

test("reads verify replies, and each action posts exactly one request with the research header", async () => {
  assert.deepEqual(await withFetch(200, paid, () => fetchResearch(paid.request_id)), { state: "ready", data: paid });
  const moved = copy(paid);
  moved.result!.analysis!.established[0].quotes[0].end += 2;
  assert.equal((await withFetch(200, moved, () => fetchResearch(paid.request_id))).state, "error");
  assert.deepEqual(await withFetch(404, { detail: "Unknown research request ID" }, () => fetchResearch("x")),
                   { state: "missing", message: "Unknown research request ID" });

  const seen: { url: string; init?: RequestInit }[] = [];
  const done = await withFetch(201, { ...prepared, created: true }, () => prepareResearch(prepared.capture_id), seen);
  assert.equal(done.state, "saved");
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, "/api/research-analyses");
  assert.equal((seen[0].init?.headers as Record<string, string>)["X-Second-Order-Research"], "1");
  assert.deepEqual(JSON.parse(String(seen[0].init?.body)), { capture_id: prepared.capture_id });

  const paidSeen: { url: string; init?: RequestInit }[] = [];
  const reply = { flow_version: "research-analysis-flow-0.1", request_id: prepared.request_id, mode: "paid",
                  outcome: "analysis", provider_called: true, cost_usd: 0.015 };
  const estimate = prepared.cost_estimate.estimated_real_run_if_output_reaches_max_usd;
  assert.equal((await withFetch(201, reply, () => sendPaid(prepared.request_id, prepared.request_sha256, estimate),
                                paidSeen)).state, "saved");
  assert.deepEqual(JSON.parse(String(paidSeen[0].init?.body)), {
    request_sha256: prepared.request_sha256, approve_paid_request: true, estimated_max_usd: estimate });
  assert.equal(paidSeen.length, 1);
  const refused = await withFetch(409, { detail: "This research request already has an attempt" },
                                  () => sendMock(prepared.request_id, prepared.request_sha256, "analysis"));
  assert.deepEqual(refused, { state: "failed", message: "This research request already has an attempt" });
  const lost = await withFetch(500, { detail: "interrupted" },
                               () => sendMock(prepared.request_id, prepared.request_sha256, "analysis"));
  assert.equal(lost.state, "unconfirmed");
});

test("the research page has its own address under the saved event, and history counts research apart", () => {
  const id = prepared.capture_id;
  assert.deepEqual(matchRoute(`/events/capture/${id}/research`), { page: "research-analysis", captureId: id });
  assert.deepEqual(matchRoute(`/events/capture/${id}/research/`), { page: "research-analysis", captureId: id });
  assert.deepEqual(matchRoute("/events/capture/%E0%A4/research"), { page: "not-found", reason: "malformed" });
  assert.deepEqual(matchRoute(`/events/inbox/${id}/research`), { page: "not-found", reason: "unknown" });
  assert.deepEqual(matchRoute(`/events/capture/${id}`), { page: "event-overview", kind: "capture", id });
  assert.equal(researchHref(id), `/events/capture/${id}/research`);
  const history: ProcessingHistory = {
    history_version: "event-history-0.1", provider_called: false, state: "processed",
    summary: { retrievals: 1, versions: 1, model_triage: 0, simulated_triage: 0, triage_requests: 0, captures: 1,
               drafts: 0, reviews: 0, frozen: 0, uncertain: 0, failed: 0, research_requests: 1, research_results: 1,
               research_reviews: 2 },
    steps: [], limitations: [] };
  assert.equal(historyStatement(history), "Listed by 1 recorded retrieval; 1 saved event, 1 research request prepared, " +
    "1 recorded research result, 2 research review versions.");
});

test("a user account's request is read on the operator page only with its Effort, account and own reviews", () => {
  const user = copy(prepared) as unknown as Record<string, unknown>;
  const id = `${prepared.request_id}.high`;
  Object.assign(user, { request_id: id, request_version: "research-request-0.2", prepared_by: "u-0123456789abcdef",
                        effort: "high", attempt: { ...prepared.attempt, request_id: id } });
  assert.equal(problem(user), null);
  assert.ok(problem({ ...user, prepared_by: null }));                          // A user's request names its account.
  assert.ok(problem({ ...user, effort: "low" }));                              // Its Effort is the one in its ID.
  assert.ok(problem({ ...user, request_version: "research-request-0.1" }));    // And it is research-request-0.2.
  assert.ok(problem({ ...copy(prepared), prepared_by: "u-0123456789abcdef" })); // An operator request names none.
  const withOperatorReview = { ...user, reviews: { state: "verified", problem: null,
    records: [{ ...copy(reviewed.reviews.records[0]), request_id: id }] } };
  assert.match(problem(withOperatorReview) ?? "", /does not follow/);           // Its reviews are research-review-0.2.
  const listed = copy(listing) as { requests: Record<string, unknown>[] };
  listed.requests.push({ request_id: `${reviewed.capture_id}.research-prompt-1.low`, state: "verified" });
  assert.ok("listing" in readListing(listed, reviewed.capture_id));
});
