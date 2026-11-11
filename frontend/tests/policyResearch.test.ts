// Research views, against replies the backend serves (captured by tests/test_policy_research.py into
// fixtures/policy-research-*.json): a SYNTHETIC view whose sources all check, the same view with one release written
// against another version, and the committed semiconductor view on a machine without the retained sources. Replies are
// read fail-closed: a comparison shows an observation only when every release it compares checked, its evidence must
// cite those releases, and counts reconcile with states.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { matchRoute } from "../src/routes.ts";
import {
  RESEARCH_VIEW_VERSION, fetchResearch, isResearchView, pressReleaseLink, stageColumns, statedDate, statedDates,
  statusesOf, type ResearchView,
} from "../src/policyResearch.ts";
import { isCatalog, type Catalog } from "../src/researchCatalog.ts";

const fixture = <T>(name: string): T => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const available = fixture<ResearchView>("policy-research-available.json");
const revalidation = fixture<ResearchView>("policy-research-revalidation.json");
const unavailable = fixture<ResearchView>("policy-research-unavailable.json");
const catalog = fixture<Catalog>("policy-research-catalog.json");
const copy = <T>(value: T): T => structuredClone(value);
const SYNTHETIC = "synthetic-policy";
const REAL = "semiconductor-policy";

async function withFetch<T>(status: number, body: unknown, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

test("the served views are read and their states reconcile", () => {
  assert.equal(available.view_version, RESEARCH_VIEW_VERSION);
  assert.equal(isResearchView(available, SYNTHETIC), true);
  assert.equal(isResearchView(revalidation, SYNTHETIC), true);
  assert.equal(isResearchView(unavailable, REAL), true);
  assert.equal(isCatalog(catalog), true);
  assert.deepEqual(available.counts.comparisons, { available: 2, needs_revalidation: 0, unavailable: 0 });
  assert.deepEqual(revalidation.counts.comparisons, { available: 1, needs_revalidation: 1, unavailable: 0 });
  assert.deepEqual(unavailable.counts.comparisons, { available: 0, needs_revalidation: 0, unavailable: 7 });
  assert.equal(isResearchView(available, REAL), false);  // A reply for another view is not this one.
});

test("a comparison shows its observation only when every release it compares checked", () => {
  const shown = copy(revalidation);
  const withheld = shown.comparisons.find((item) => item.state === "needs_revalidation")!;
  withheld.observation = "Shown anyway.";
  assert.equal(isResearchView(shown, SYNTHETIC), false);
  const claimed = copy(revalidation);
  claimed.comparisons.find((item) => item.state === "needs_revalidation")!.state = "available";
  claimed.counts.comparisons = { available: 2, needs_revalidation: 0, unavailable: 0 };
  assert.equal(isResearchView(claimed, SYNTHETIC), false);
  const missing = copy(unavailable);
  missing.comparisons[0].state = "needs_revalidation";  // A missing source makes a comparison unavailable.
  missing.counts.comparisons = { available: 0, needs_revalidation: 1, unavailable: 6 };
  assert.equal(isResearchView(missing, REAL), false);
});

test("evidence must cite the compared releases and their real paragraphs", () => {
  const outside = copy(available);
  outside.comparisons[0].evidence![0].publication = "synthetic-first";
  assert.equal(isResearchView(outside, SYNTHETIC), false);
  const beyond = copy(available);
  const quote = beyond.comparisons[0].evidence!.find((item) => item.kind === "quote")!;
  quote.paragraph = quote.paragraphs + 1;
  assert.equal(isResearchView(beyond, SYNTHETIC), false);
  const uncited = copy(available);
  uncited.comparisons[0].evidence = uncited.comparisons[0].evidence!.filter((item) =>
    item.publication === "synthetic-rule");
  assert.equal(isResearchView(uncited, SYNTHETIC), false);
});

test("statements keep their status and nothing silent carries a quote", () => {
  const rule = available.publications[0];
  assert.deepEqual(statusesOf(rule.dimensions!.timing), ["stated", "not_stated"]);
  const quoted = copy(available);
  quoted.publications[1].dimensions!.timing.statements[0].excerpts = [{ paragraph: 1, quote: "Anything." }];
  assert.equal(isResearchView(quoted, SYNTHETIC), false);
  const staged = copy(available);
  staged.publications[1].dimensions!.supply_chain.statements[0].status = "stated";
  assert.equal(isResearchView(staged, SYNTHETIC), false);
  const unreferenced = copy(available);
  unreferenced.publications[0].dimensions!.conditions.statements[0].reference = "not-declared";
  assert.equal(isResearchView(unreferenced, SYNTHETIC), false);
  const short = copy(available);
  delete (short.publications[1].dimensions as Record<string, unknown>).parties;
  assert.equal(isResearchView(short, SYNTHETIC), false);
});

test("dates keep their precision and a dateline only comes from a checked release page", () => {
  const dates = statedDates(available.publications[0]);
  assert.deepEqual(dates.map(statedDate), ["2 Mar 2026", "“30 days after publication”"]);
  assert.equal(available.publications[0].dateline!.value, "January 10, 2026");
  assert.equal(available.publications[1].dateline, null);
  const invented = copy(unavailable);
  const paged = invented.publications.find((item) => item.dateline !== null)!;
  paged.dateline!.value = "October 7, 2022";  // A page that did not check shows no dateline.
  assert.equal(isResearchView(invented, REAL), false);
  const checked = copy(unavailable);
  checked.publications[0].text.status = "checked";
  assert.equal(isResearchView(checked, REAL), false);
});

test("same-titled releases stay separate and the stage grid reads the curator's stages", () => {
  const [first, second] = available.publications.slice(2);
  assert.equal(first.title, second.title);
  assert.notEqual(first.url, second.url);
  const columns = stageColumns(available);
  assert.deepEqual(columns.find((column) => column.stage === "chips")!.named, new Set(["synthetic-rule"]));
  assert.deepEqual(columns.find((column) => column.stage === "equipment")!.named, new Set(["synthetic-update"]));
  const merged = copy(available);
  merged.publications[3].id = merged.publications[2].id;
  assert.equal(isResearchView(merged, SYNTHETIC), false);
});

test("without the retained sources nothing is shown as checked", () => {
  assert.equal(unavailable.snapshot.state, "missing");
  assert.equal(unavailable.snapshot.filter_matches, null);
  assert.ok(unavailable.publications.every((item) => item.dimensions === null && item.stages === null));
  assert.equal(stageColumns(unavailable).every((column) => column.named.size === 0), true);
  const leaked = copy(unavailable);
  leaked.publications[0].dimensions = available.publications[0].dimensions;
  assert.equal(isResearchView(leaked, REAL), false);
});

test("only BIS press-release addresses are linked, and counts must reconcile", () => {
  assert.equal(pressReleaseLink("https://www.bis.gov/press-release/x-y"), true);
  assert.equal(pressReleaseLink("https://www.bis.gov.example/press-release/x"), false);
  assert.equal(pressReleaseLink("javascript:alert(1)"), false);
  const foreign = copy(available);
  foreign.publications[0].url = "https://example.invalid/press-release/x";
  assert.equal(isResearchView(foreign, SYNTHETIC), false);
  const miscounted = copy(available);
  miscounted.counts.publications.verified = 3;
  assert.equal(isResearchView(miscounted, SYNTHETIC), false);
  const reordered = copy(available);
  reordered.publications.reverse();
  assert.equal(isResearchView(reordered, SYNTHETIC), false);
});

test("the client reads a view or says why it cannot", async () => {
  const signal = new AbortController().signal;
  assert.equal((await withFetch(200, available, () => fetchResearch(SYNTHETIC, signal))).state, "ready");
  assert.equal((await withFetch(404, { detail: "No research view has this id" },
    () => fetchResearch("nope", signal))).state, "missing");
  const broken = await withFetch(200, { ...available, provider_called: true }, () => fetchResearch(SYNTHETIC, signal));
  assert.equal(broken.state, "error");
});

test("research views are addressed under the case library", () => {
  assert.deepEqual(matchRoute("/library/research/semiconductor-policy"), { page: "research", id: REAL });
  assert.deepEqual(matchRoute("/library/research/semiconductor-policy/"), { page: "research", id: REAL });
  assert.deepEqual(matchRoute("/library/research/%E0%A4"), { page: "not-found", reason: "malformed" });
  assert.deepEqual(matchRoute("/library/research/a/b"), { page: "not-found", reason: "unknown" });
  assert.deepEqual(catalog.views.map((view) => view.href), [`/library/research/${SYNTHETIC}`]);
});
