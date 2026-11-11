// The News desk's brief editor format (src/admin/newsDesk.ts) over the SYNTHETIC stories fixture: a brief turns into the
// editor's lines and back unchanged, a fact names the material reports it rests on by number, and a line that does not
// parse is reported, never dropped or guessed. The Admin build registers the News desk screen.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ADMIN_SCREENS, SCREEN_LABEL, adminScreen } from "../src/admin/adminFormat.ts";
import { fromEditor, toEditor, type Material } from "../src/admin/newsDesk.ts";

const story = JSON.parse(readFileSync(new URL("./fixtures/stories-contract-story.json", import.meta.url), "utf8")).story;
const material: Material = {
  material_sha256: "0".repeat(64), statement: story.brief.material.statement, coverage: story.brief.material.coverage,
  reports: story.brief.material.reports.map((row: { entry_id: string; publisher: string; title: string }) =>
    ({ ...row, excerpt: null })), not_used: [],
};

test("a brief turns into the editor's lines and back unchanged", () => {
  const text = toEditor(story.brief.content, material);
  assert.match(text.facts, /\[1\]$/);
  assert.match(text.themes, /^sector \| Steel \| /);
  const back = fromEditor(text, material);
  assert.deepEqual(back.problems, []);
  // The editor's lines carry the brief, not its economic explanation (prepared through a batch; the desk says so).
  const { economics, ...brief } = story.brief.content;
  assert.ok(economics);
  assert.deepEqual(back.content, brief);
  const desk = readFileSync(new URL("../src/admin/AdminNewsStory.tsx", import.meta.url), "utf8");
  assert.match(desk, /data-economics-note/);
});

test("a fact without its reports and a malformed theme are reported, never dropped", () => {
  const text = toEditor(story.brief.content, material);
  const missing = fromEditor({ ...text, facts: "A fact with no report numbers" }, material);
  assert.equal(missing.content, null);
  assert.match(missing.problems[0], /^Fact 1 must end with the numbers/);
  const unknown = fromEditor({ ...text, facts: "A fact [9]" }, material);
  assert.equal(unknown.content, null);
  const theme = fromEditor({ ...text, themes: "stock | Steel | x" }, material);
  assert.match(theme.problems[0], /^Theme 1 must be/);
  const blank = fromEditor({ ...text, implications: "\n  \nCould matter if it lasts.\n" }, material);
  assert.deepEqual(blank.content?.implications, [{ text: "Could matter if it lasts." }]);
});

test("the Admin build has a News desk screen", () => {
  assert.ok((ADMIN_SCREENS as readonly string[]).includes("news"));
  assert.equal(SCREEN_LABEL.news, "News desk");
  assert.equal(adminScreen("/admin/news"), "news");
});

test("the desk's relevance panel names every relevance state and every editor's verdict, and its routes", async () => {
  const { RELEVANCE_STATES } = await import("../src/contracts/stories.ts");
  const { newsPaths } = await import("../src/admin/newsDesk.ts");
  const panel = readFileSync(new URL("../src/admin/AdminNewsRelevance.tsx", import.meta.url), "utf8");
  const labels = panel.slice(panel.indexOf("RELEVANCE_LABEL"), panel.indexOf("const BASIS_LABEL"));
  for (const state of RELEVANCE_STATES) assert.match(labels, new RegExp(`\\b${state}:`), state);
  for (const verdict of ["relevant", "outside_scope", "insufficient_information", "cleared"]) {
    assert.ok(panel.includes(`["${verdict}",`), verdict);
  }
  assert.equal(newsPaths.relevance, "/api/admin/news/relevance");
  assert.equal(newsPaths.relevanceBatchAction("rbatch-0123456789abcdef", "approval"),
               "/api/admin/news/relevance/batches/rbatch-0123456789abcdef/approval");
  assert.equal(newsPaths.story("story-0123456789abcdef", "relevance"),
               "/api/admin/news/stories/story-0123456789abcdef/relevance");
});

test("a failed draft attempt shows the provider's request ID and bounded message, and older attempts show nothing", async () => {
  const { providerNote } = await import("../src/admin/newsDesk.ts");
  const base = { state: "provider_error", detail: "The model provider returned HTTP 400 (invalid_request_error); no " +
                 "draft was produced", version: null };
  assert.equal(providerNote({ ...base, request_id: "req_SYNTHETIC0001", provider_error: { http_status: 400,
    error_type: "invalid_request_error", message: "SYNTHETIC: a field is invalid.", message_truncated: false,
    request_id: "req_SYNTHETIC0001" } }),
    "Provider request ID req_SYNTHETIC0001. Provider message: SYNTHETIC: a field is invalid.");
  assert.equal(providerNote({ ...base, request_id: null, provider_error: { http_status: 529, error_type: null,
    message: null, message_truncated: false, request_id: null } }), null);
  assert.equal(providerNote(base), null);  // Recorded before diagnostics were kept: nothing is invented.
});

test("each stage of a two-stage draft says its estimate, limit and state, and a planned estimate says so", async () => {
  const { stageLine } = await import("../src/admin/newsDesk.ts");
  const estimate = (usd: number) => ({ estimated_real_run_if_output_reaches_max_usd: usd, caveat: "SYNTHETIC" });
  const first = { stage: 1 as const, name: "Evidence and figures", does: "SYNTHETIC", stage_version: "brief-evidence-1",
                  draft_id: "brief-s1-0123456789abcdef", request_sha256: "0".repeat(64), max_tokens: 6000,
                  estimate: estimate(0.0731), estimate_kind: "exact" as const,
                  attempt: { state: "validated", detail: null, version: null }, usage_cost: { usd: 0.0048 } };
  assert.equal(stageLine(first), "Stage 1, evidence and figures: planning estimate $0.0731, at most 6,000 output " +
    "tokens · validated · reported usage $0.0048.");
  const second = { ...first, stage: 2 as const, name: "Interpretation and brief", draft_id: null,
                   request_sha256: null, max_tokens: 9500, estimate: estimate(0.1283), estimate_kind: "planned" as const,
                   attempt: null, usage_cost: null };
  assert.equal(stageLine(second), "Stage 2, interpretation and brief: planned estimate $0.1283, at most 9,500 " +
    "output tokens · prepared after stage 1 passes, approved on its own.");
  assert.equal(stageLine({ ...second, estimate: null, estimate_kind: "not_needed" as const }),
               "Stage 2, interpretation and brief: not needed, at most 9,500 output tokens.");
});
