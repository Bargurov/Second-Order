// Assessment client logic: replies read fail-closed, joins by explicit IDs only, no default chosen by result, and a lost
// reply that is never resent.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  ASSESSMENT_VERSION, DOSSIER_VERSION, RETRIEVAL_PLAN_VERSION, approveAssessment, assessmentHref, isAssessmentPreview,
  isLifecycleDossier, isRecorded, isRetrievalPlan, latestByRecordTime, lifecycleDossierHref, linkForDraft, versioned,
  type AssessmentPreview, type AssessmentRow, type DraftLinks,
} from "../src/assessment.ts";
import { matchRoute } from "../src/routes.ts";

const H = "a".repeat(64);
const E = "e".repeat(64);
const S = "5".repeat(64);
const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; });

function preview(changes: Record<string, unknown> = {}, binding: Record<string, unknown> = {}) {
  return {
    assessment_version: ASSESSMENT_VERSION, preview_sha256: "f".repeat(64), assessable: true, blockers: [],
    written: false, evaluated: false, provider_called: false, hypothesis: { hypothesis_id: H }, outcome: { snapshot_id: S },
    binding: { hypothesis_id: H, outcome_snapshot_id: S, cutoff: "2026-10-01T12:00:01+00:00", prior_assessments: [],
               reassessment: false, ...binding },
    ...changes,
  };
}
const read = (body: unknown) => versioned(body, "assessment_version", ASSESSMENT_VERSION, isAssessmentPreview);

test("an assessment preview is read only when it binds what it shows, writes nothing and carries no result", () => {
  assert.equal(read(preview()), true);
  assert.equal(read({ ...preview(), assessment_version: "lifecycle-assessment-0.0" }), false);
  assert.equal(read(preview({ blockers: ["Horizon not elapsed."] })), false);  // assessable must agree.
  assert.equal(read(preview({ evaluated: true })), false);
  assert.equal(read(preview({ written: true })), false);
  assert.equal(read(preview({}, { outcome_snapshot_id: "6".repeat(64) })), false);  // Another outcome than shown.
  assert.equal(read(preview({}, { hypothesis_id: "b".repeat(64) })), false);
  assert.equal(read(preview({}, { prior_assessments: [E] })), false);  // A reassessment must say so.
  assert.equal(read(preview({}, { prior_assessments: [E], reassessment: true })), true);
  assert.equal(read(preview({}, { cutoff: null })), false);  // Nothing is assessable without the server's cutoff.
  assert.equal(read(preview({ assessable: false, blockers: ["Outcome data missing."] }, { cutoff: null })), true);
});

test("a recorded reply and a prepared Dossier are read only for exactly the assessment asked for", () => {
  const recorded = { assessment_version: ASSESSMENT_VERSION, state: "recorded", evaluation_id: E, headline: "x",
                     dossier: { state: "prepared" } };
  assert.equal(versioned(recorded, "assessment_version", ASSESSMENT_VERSION, isRecorded), true);
  assert.equal(versioned({ ...recorded, evaluation_id: "short" }, "assessment_version", ASSESSMENT_VERSION, isRecorded),
               false);
  const dossier = { dossier_version: DOSSIER_VERSION, hypothesis_id: H, evaluation_id: E, snapshots: {},
                    view: { id: H, evaluation_id: E, state: "evaluated" } };
  assert.equal(isLifecycleDossier(dossier, H, E), true);
  assert.equal(isLifecycleDossier(dossier, H, "d".repeat(64)), false);
  assert.equal(isLifecycleDossier({ ...dossier, view: { ...dossier.view, evaluation_id: "d".repeat(64) } }, H, E), false);
  assert.equal(isLifecycleDossier({ ...dossier, view: { ...dossier.view, state: "not_evaluated" } }, H, E), false);
});

test("a retrieval plan states exactly one request or none, consistently", () => {
  const plan = { plan_version: RETRIEVAL_PLAN_VERSION, plan_sha256: "c".repeat(64), hypotheses: [], requests: 1,
                 request: { url: "x" }, awaiting_release: [], next_attempt: 1 };
  assert.equal(isRetrievalPlan(plan), true);
  assert.equal(isRetrievalPlan({ ...plan, awaiting_release: undefined }), false);  // The release split is required.
  assert.equal(isRetrievalPlan({ ...plan, requests: 0, request: null,
                                 awaiting_release: [{ session: "2026-12-17", obtainable_from: "x" }] }), true);
  assert.equal(isRetrievalPlan({ ...plan, plan_version: "lifecycle-outcome-plan-0.1" }), false);  // An older scope.
  assert.equal(isRetrievalPlan({ ...plan, request: null }), false);
  assert.equal(isRetrievalPlan({ ...plan, requests: 0 }), false);
  assert.equal(isRetrievalPlan({ ...plan, requests: 0, request: null }), true);
  assert.equal(isRetrievalPlan({ ...plan, plan_version: "market-retrieval-plan-0.2" }), false);  // Another scope.
});

test("a draft's freeze is joined by its recorded draft ID only, never by headline", () => {
  const links: DraftLinks = { lifecycle_version: "lifecycle-freeze-0.1", problems: [], note: "", links: [{
    draft_id: "d".repeat(64), capture_id: "c", hypothesis_id: H, action_id: "f".repeat(64), frozen_at: "2026-10-11T14:00:00+00:00",
    headline: "Same headline", draft_view_sha256: "9".repeat(64),
    review_at_freeze: { review_id: "r", sequence: 1, status: "human_reviewed", saved_at: "x", attributed_to: "y" } }] };
  assert.equal(linkForDraft(links, "d".repeat(64))?.hypothesis_id, H);
  assert.equal(linkForDraft(links, "e".repeat(64)), null);  // Another draft with the same headline is not linked.
});

test("the latest assessment is chosen by record time, never by its result", () => {
  const row = (recorded_at: string, verdict: string, id: string) => ({ recorded_at, verdict, evaluation_id: id }) as AssessmentRow;
  const rows = [row("2026-10-01T13:00:00+00:00", "supported", "1".repeat(64)),
                row("2026-10-02T13:00:00+00:00", "contradicted", "2".repeat(64))];
  assert.equal(latestByRecordTime(rows)?.verdict, "contradicted");
  assert.equal(latestByRecordTime([...rows].reverse())?.verdict, "contradicted");
  assert.equal(latestByRecordTime([]), null);
});

test("assessment and Dossier addresses route to their pages, and malformed ones are Not Found", () => {
  assert.deepEqual(matchRoute(assessmentHref(H, E)), { page: "hypothesis-assessment", id: H, evaluationId: E });
  assert.deepEqual(matchRoute(lifecycleDossierHref(H, E)), { page: "hypothesis-dossier", id: H, evaluationId: E });
  assert.deepEqual(matchRoute(`/hypotheses/${H}/assessments/%E0%A4%A`), { page: "not-found", reason: "malformed" });
  assert.deepEqual(matchRoute(`/hypotheses/${H}/other/${E}`), { page: "not-found", reason: "unknown" });
  assert.deepEqual(matchRoute(`/hypotheses/${H}`), { page: "hypothesis", id: H });
});

test("a lost reply to Evaluate and prepare Dossier is unconfirmed and never sent again", async () => {
  let calls = 0;
  globalThis.fetch = (async () => { calls += 1; throw new TypeError("network down"); }) as typeof fetch;
  const result = await approveAssessment(preview() as unknown as AssessmentPreview, false);
  assert.equal(result.state, "unconfirmed");
  assert.equal(calls, 1);
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500 })) as typeof fetch;
  assert.equal((await approveAssessment(preview() as unknown as AssessmentPreview, false)).state, "unconfirmed");
});

test("a refused approval carries the server's new preview only when it can be read", async () => {
  const fresh = preview({ preview_sha256: "1".repeat(64) }, { prior_assessments: [E], reassessment: true });
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "changed", preview: fresh }), { status: 409 })) as typeof fetch;
  const refused = await approveAssessment(preview() as unknown as AssessmentPreview, false);
  assert.equal(refused.state, "refused");
  assert.equal(refused.state === "refused" && refused.preview?.preview_sha256, "1".repeat(64));
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "changed", preview: { ...fresh, written: true } }),
                                               { status: 409 })) as typeof fetch;
  const unread = await approveAssessment(preview() as unknown as AssessmentPreview, false);
  assert.equal(unread.state === "refused" && unread.preview, null);
});
