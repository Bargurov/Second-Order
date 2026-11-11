// The retained BIS snapshot client, against views the backend serves for a SYNTHETIC snapshot (captured by
// tests/test_bis_snapshot.py into fixtures/bis-snapshot-*.json). Replies are read fail-closed: counts reconcile with
// rows, every address is a BIS press release, a preview and an import answer for exactly the selected records in
// order, and the Inbox accepts imported entries only with their snapshot provenance.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { entryLink, fetchInbox, officialLink, prefilledFields, type InboxItem, type InboxView } from "../src/inbox.ts";
import { matchRoute } from "../src/routes.ts";
import {
  DEFAULT_FILTER, SNAPSHOT_VIEW_VERSION, filteredRows, isImportResult, isPreview, isRecordView, isSnapshotView,
  pressReleaseLink, toggledKey, type ImportResult, type Preview, type RecordView, type SnapshotView,
} from "../src/snapshot.ts";

const fixture = <T>(name: string): T => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const view = fixture<SnapshotView>("bis-snapshot-view.json");
const record = fixture<RecordView>("bis-snapshot-record.json");
const preview = fixture<Preview>("bis-snapshot-preview.json");
const done = fixture<ImportResult>("bis-snapshot-import.json");
const inbox = fixture<InboxView>("bis-snapshot-inbox.json");
const copy = <T>(value: T): T => structuredClone(value);
const previewKeys = preview.rows.map((row) => row.key);
const importKeys = done.rows.map((row) => row.key);

async function withFetch<T>(body: unknown, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => new Response(JSON.stringify(body), { status: 200 })) as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

test("the served views are read and reconcile", () => {
  assert.equal(view.view_version, SNAPSHOT_VIEW_VERSION);
  assert.equal(isSnapshotView(view), true);
  assert.equal(isRecordView(record, record.record.key), true);
  assert.equal(isPreview(preview, previewKeys), true);
  assert.equal(isImportResult(done, importKeys), true);
  assert.equal(view.state, "open");
  assert.equal(view.counts!.usable, view.rows.length);
  assert.deepEqual(preview.counts, { new: 2, existing: 0, changed: 0, unusable: 1 });
  assert.deepEqual([done.counts.added, done.written], [2, true]);
});

test("a view that does not reconcile, or carries an address off BIS's press releases, is refused", () => {
  const broken: ((body: SnapshotView) => void)[] = [
    (body) => { body.counts!.usable += 1; },
    (body) => { body.counts!.filters.semiconductors += 1; },
    (body) => { body.counts!.completeness.checked += 1; },
    (body) => { body.counts!.dates.missing += 1; },
    (body) => { body.rows[0].link = "https://www.bis.gov/news/elsewhere"; },
    (body) => { body.rows[0].link = "https://example.invalid/press-release/x"; },
    (body) => { body.rows[0].id = "wto-news:" + body.rows[0].key; },
    (body) => { body.rows[1].key = body.rows[0].key; body.rows[1].id = body.rows[0].id; },
    (body) => { body.rows[0].date = "2026-09-30T16:00:00+00:00"; },
    (body) => { (body.rows[0] as { completeness: string }).completeness = "verified"; },
    (body) => { (body as { provider_called: boolean }).provider_called = true; },
    (body) => { body.package!.sha256 = "abc"; },
  ];
  for (const change of broken) {
    const changed = copy(view);
    change(changed);
    assert.equal(isSnapshotView(changed), false, change.toString());
  }
});

test("a preview or import must answer for exactly the selection, in order", () => {
  assert.equal(isPreview(preview, [...previewKeys].reverse()), false);
  assert.equal(isPreview(preview, previewKeys.slice(1)), false);
  const miscounted = copy(preview); miscounted.counts.new = 3;
  assert.equal(isPreview(miscounted, previewKeys), false);
  const noWrites = copy(preview); noWrites.writes = false;
  assert.equal(isPreview(noWrites, previewKeys), false);
  const unwritten = copy(done); unwritten.written = false;
  assert.equal(isImportResult(unwritten, importKeys), false);
  const idWithoutWrite = copy(done); idWithoutWrite.rows.forEach((row) => { row.outcome = "reused"; });
  idWithoutWrite.counts = { added: 0, version_added: 0, reused: 2, kept: 0, unusable: 0, conflict: 0 };
  idWithoutWrite.written = false;
  assert.equal(isImportResult(idWithoutWrite, importKeys), false);  // A reused-only import has no import id.
  idWithoutWrite.import_id = null;
  assert.equal(isImportResult(idWithoutWrite, importKeys), true);
  assert.equal(isRecordView(record, "0".repeat(20)), false);
  const outside = copy(record);
  outside.record.publisher.external_link = { url: "http://justice.gov/x", host: "justice.gov", title: null };
  assert.equal(isRecordView(outside, record.record.key), false);
});

test("browsing starts with semiconductor records, and every filter narrows locally", () => {
  const first = filteredRows(view.rows, DEFAULT_FILTER);
  assert.ok(first.length > 0 && first.every((row) => row.filters.semiconductors));
  assert.equal(first.length, view.counts!.filters.semiconductors);
  const all = filteredRows(view.rows, { ...DEFAULT_FILTER, filter: "all" });
  assert.equal(all.length, view.rows.length);
  const dated = all.filter((row) => row.date !== null).map((row) => row.date!);
  assert.deepEqual(dated, [...dated].sort().reverse());
  assert.equal(all.at(-1)!.date === null || all.every((row) => row.date !== null), true);
  assert.deepEqual(filteredRows(view.rows, { ...DEFAULT_FILTER, filter: "all", query: "ion implanters" })
    .map((row) => row.title), ["Synthetic Settlement over Ion Implanters"]);
  assert.ok(filteredRows(view.rows, { ...DEFAULT_FILTER, filter: "all", text: "title_only" })
    .every((row) => row.completeness === "title_only" || row.completeness === "unreadable"));
  assert.ok(filteredRows(view.rows, { ...DEFAULT_FILTER, filter: "all", state: "new" })
    .every((row) => row.import.state === "new"));
  assert.ok(filteredRows(view.rows, { ...DEFAULT_FILTER, filter: "all", topic: "No topic" })
    .every((row) => row.topics.length === 0));
});

test("a selection never exceeds its limit", () => {
  let selected: string[] = [];
  for (let n = 0; n < 30; n++) selected = toggledKey(selected, n.toString(16).padStart(20, "0"), 25);
  assert.equal(selected.length, 25);
  assert.equal(toggledKey(selected, selected[0], 25).length, 24);
});

test("only plain https press-release addresses on BIS's site are links", () => {
  assert.equal(pressReleaseLink("https://www.bis.gov/press-release/st.-lucia-0"), true);
  for (const url of ["http://www.bis.gov/press-release/x", "https://bis.gov/press-release/x",
                     "https://www.bis.gov/press-release/x?y=1", "https://www.bis.gov/press-release/../x",
                     "https://user@www.bis.gov/press-release/x", "https://www.bis.gov:8443/press-release/x",
                     "https://www.bis.gov/news-updates", "javascript:alert(1)", 7]) {
    assert.equal(pressReleaseLink(url), false, String(url));
  }
});

test("the Inbox accepts imported entries only with their provenance, and links them apart from the feeds", async () => {
  assert.equal((await withFetch(inbox, () => fetchInbox())).state, "ready");
  const item = inbox.imported![0] as InboxItem;
  assert.equal(entryLink(item), true);
  assert.equal(officialLink(item.link), false);  // Triage's own link check is unchanged.
  const empty = { headline: "", sourceUrl: "", publishedDate: "", publishedTime: "", publishedOffset: "", sourceText: "" };
  assert.deepEqual(prefilledFields(item, empty), { ...empty, headline: item.title, sourceUrl: item.link });
  const broken: ((body: InboxView) => void)[] = [
    (body) => { delete body.imported![0].imported; },
    (body) => { body.imported![0].source = "wto-news"; },
    (body) => { body.imported![0].link = "https://www.bis.gov/news/x"; },
    (body) => { body.imported![0].feed_timestamp.suggestion = { date: "2026-09-30", time: "16:00:00", offset: "+00:00",
                                                                dropped_fraction: null }; },
    (body) => { body.imported![0].id = "bis-snapshot:" + "0".repeat(20); },
  ];
  for (const change of broken) {
    const changed = copy(inbox);
    change(changed);
    assert.equal((await withFetch(changed, () => fetchInbox())).state, "error", change.toString());
  }
});

test("the snapshot has its own address", () => {
  assert.deepEqual(matchRoute("/inbox/bis-snapshot"), { page: "bis-snapshot" });
  assert.deepEqual(matchRoute("/inbox/bis-snapshot/"), { page: "bis-snapshot" });
  assert.deepEqual(matchRoute("/inbox/other"), { page: "not-found", reason: "unknown" });
});
