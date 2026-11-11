// Event Inbox retrieval records and processing at a glance: each recorded request in words (status, complete or
// partial body, hash, kept copy, validators, parser), what a refresh added, reused, changed or refused, which texts an
// entry holds (never the article), and the processing index read with a GET and verified. All values are SYNTHETIC.
import assert from "node:assert/strict";
import test from "node:test";
import {
  countsLine, fetchProcessing, processingLabel, refreshLines, retrievalLine, textLine, type AcquisitionSummary,
  type InboxSource,
} from "../src/inbox.ts";

const ACCEPTED: AcquisitionSummary = {
  number: 3, started_at: "2026-10-12T19:30:01+00:00", finished_at: "2026-10-12T19:30:02+00:00", outcome: "accepted",
  detail: null, endpoint: "https://www.federalreserve.gov/feeds/press_monetary.xml", http_status: 200,
  headers: { etag: '"v1"' }, validators: { etag: '"v1"', last_modified: "Mon, 12 Oct 2026 18:00:00 GMT" },
  body: { state: "complete", bytes: 9649, sha256: "a".repeat(64), declared_bytes: 9649, content_encoding: null,
          kept: `${"a".repeat(64)}.xml` },
  kept_copy: "verified", parser_version: "event-inbox-parser-0.1",
  counts: { new: 1, changed: 0, unchanged: 14, no_longer_listed: 1, skipped: 0, duplicates: 0, not_retained: 0,
            basis: "archive" },
  notes: [],
};

const source = (key: string) => ({ key, label: `Synthetic ${key}` }) as InboxSource;

test("a recorded request states its status, complete body, hash, kept copy, validators and parser", () => {
  assert.equal(retrievalLine(ACCEPTED), "Request 3, 2026-10-12 19:30 UTC: HTTP 200, body received complete, 9,649 " +
    "bytes (SHA-256 aaaaaaaaaaaa…), kept privately. Cache validators: ETag \"v1\", Last-Modified Mon, 12 Oct 2026 " +
    "18:00:00 GMT. Parsed by event-inbox-parser-0.1.");
  assert.match(retrievalLine({ ...ACCEPTED, validators: { etag: null, last_modified: null }, kept_copy: "differs" }),
               /its kept copy no longer matches its record\. The response gave no cache validators\./);
  assert.match(retrievalLine({ ...ACCEPTED, body: { ...ACCEPTED.body, content_encoding: "gzip" } }),
               /body received complete, 9,649 bytes after undoing the server's gzip encoding \(SHA-256/);
  const partial = retrievalLine({ ...ACCEPTED, outcome: "failed", detail: "The response exceeded 1000000 bytes.",
                                  body: { ...ACCEPTED.body, state: "partial", bytes: 1_250_000, kept: null },
                                  counts: null, kept_copy: null });
  assert.equal(partial, "Request 3, 2026-10-12 19:30 UTC: HTTP 200, not retrieved; 1,250,000 bytes arrived before it " +
    "stopped (SHA-256 aaaaaaaaaaaa…). The response exceeded 1000000 bytes.");
  assert.match(retrievalLine({ ...ACCEPTED, outcome: "failed", http_status: null, detail: "No answer.",
                               body: { ...ACCEPTED.body, state: "none", bytes: 0, sha256: null } }),
               /: no response, not retrieved\. No answer\.$/);
  assert.match(retrievalLine({ ...ACCEPTED, outcome: "refused", detail: "The publisher answered with a web page.",
                               counts: null }), /body received complete, 9,649 bytes .*, not accepted\. The publisher answered/);
  assert.doesNotMatch(retrievalLine(ACCEPTED), /live|published/i);
});

test("a refresh says what each source added, reused, changed or refused", () => {
  assert.equal(countsLine(ACCEPTED.counts!), "1 new, 14 unchanged, 0 changed; 1 no longer listed");
  assert.equal(countsLine({ ...ACCEPTED.counts!, skipped: 2, duplicates: 1, not_retained: 3, no_longer_listed: 0 }),
               "1 new, 14 unchanged, 0 changed; refused: 2 skipped, 1 repeated; 3 beyond the entries kept");
  const sources = ["fed-monetary", "bls-empsit", "wto-news", "bls-cpi"].map(source);
  assert.deepEqual(refreshLines([
    { source: "fed-monetary", outcome: "ok", detail: null, acquisition: ACCEPTED },
    { source: "bls-empsit", outcome: "not_requested", detail: "Not requested.", acquisition: null },
    { source: "wto-news", outcome: "failed", detail: "HTTP 503",
      acquisition: { ...ACCEPTED, outcome: "failed", http_status: 503, counts: null } },
    { source: "bls-cpi", outcome: "skipped_unreadable", detail: "Unreadable.", acquisition: null },
  ], sources), ["Synthetic fed-monetary: 1 new, 14 unchanged, 0 changed; 1 no longer listed.",
                "Synthetic bls-empsit: not requested.",
                "Synthetic wto-news: did not refresh (HTTP 503); its earlier entries are kept.",
                "Synthetic bls-cpi: not refreshed; its local record is unreadable."]);
});

test("an entry's held text is the headline and the feed's excerpt, never the article", () => {
  assert.equal(textLine({ title: "as_supplied", excerpt: "shortened" }, false),
               "Held text: the headline as the feed supplies it; the feed's excerpt, shortened here at 1,200 characters. " +
               "An excerpt is not the article, and the article was not retrieved.");
  const wto = textLine({ title: "shortened", excerpt: "repeats_title" }, true);
  assert.match(wto, /shortened here at 300 characters; no excerpt \(the feed's description repeats the headline\)/);
  assert.match(wto, /full-article element, which is never read or shown\.$/);
  assert.equal(textLine(undefined, false), "Held text: not stated for this entry.");
});

test("processing at a glance: not processed is a state, and simulated triage is never a model result", () => {
  const row = { model_triage: false, simulated_triage: false, triage_attention: false, triage_requests: 0, captures: 0 };
  assert.deepEqual(processingLabel(undefined), { label: "Not processed", tone: "none" });
  assert.deepEqual(processingLabel(row), { label: "Not processed", tone: "none" });
  assert.deepEqual(processingLabel({ ...row, simulated_triage: true, triage_requests: 1 }),
                   { label: "Simulated triage only", tone: "done" });
  assert.deepEqual(processingLabel({ ...row, model_triage: true, simulated_triage: true, triage_requests: 2, captures: 2 }),
                   { label: "Model triage saved · 2 saved events", tone: "done" });
  assert.deepEqual(processingLabel({ ...row, triage_attention: true, triage_requests: 1 }),
                   { label: "Triage failed or uncertain", tone: "warn" });
  assert.deepEqual(processingLabel({ ...row, triage_requests: 1 }), { label: "Triage prepared, not sent", tone: "none" });
});

test("the processing index is read with a GET and verified before use", async () => {
  const good = { index_version: "event-processing-index-0.1", provider_called: false, items: {},
                 unreadable_triage_requests: 0, unverified_links: 0 };
  const seen: string[] = [];
  const original = globalThis.fetch;
  const reply = (body: unknown) => (async (url: RequestInfo | URL, init?: RequestInit) => {
    seen.push(`${init?.method ?? "GET"} ${String(url)}`);
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  try {
    globalThis.fetch = reply(good);
    assert.equal((await fetchProcessing()).state, "ready");
    globalThis.fetch = reply({ ...good, provider_called: true });
    assert.equal((await fetchProcessing()).state, "error");
    globalThis.fetch = reply({ ...good, index_version: "other" });
    assert.equal((await fetchProcessing()).state, "error");
  } finally {
    globalThis.fetch = original;
  }
  assert.deepEqual(seen, ["GET /api/events/processing", "GET /api/events/processing", "GET /api/events/processing"]);
});
