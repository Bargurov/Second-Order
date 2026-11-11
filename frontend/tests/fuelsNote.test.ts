// The fuels page's note helpers (fuelsNote.ts) against replies captured from the server on SYNTHETIC data.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ANALYSIS_KINDS, ANALYSIS_SECTIONS, authorship, noNewerText, noteRowLine, prose, publishedText, refreshedText }
  from "../src/fuelsNote.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf-8"));

test("an unbound note's prose is never returned, so its raw placeholders never reach the page", () => {
  const note = fixture("fuels-view-missing.json").note;
  assert.equal(note.state, "unbound");
  assert.match(note.lede, /\{brent\}/);
  assert.equal(prose(note), null);
  assert.equal(prose({ ...note, state: "none" }), null);
});

test("a placed note's prose is returned only when it is fully filled", () => {
  const note = fixture("fuels-view.json").note;
  assert.equal(prose(note)?.lede, "SYNTHETIC lede: Brent at $80.00, +$0.96 since 2 Nov 2026; the crack is $32.00.");
  assert.equal(prose(fixture("fuels-view-earlier.json").note)?.headline, "SYNTHETIC headline for a test note");
  assert.equal(prose({ ...note, lede: "Brent at {brent}." }), null);
  assert.equal(prose({ ...note, columns: { ...note.columns, stocks: "" } }), null);
  assert.equal(prose({ ...note, columns: null }), null);
});

test("an earlier note states then and now, verbatim", () => {
  assert.equal(refreshedText(fixture("fuels-view-earlier.json").note),
    "Prices have been refreshed since this note: Brent then $80.00, now $115.00; crack then $32.00, now −$3.00.");
});

test("an earlier note on the latest barrel's date adds that no newer observation has been published", () => {
  const view = fixture("fuels-view-earlier.json");
  assert.equal(view.note.observation_date, view.barrel.date);  // the synthetic refresh brought no newer date
  assert.equal(noNewerText(view.note, view.barrel), "The latest refresh found no observation newer than 3 Nov 2026.");
  assert.equal(noNewerText(view.note, { ...view.barrel, date: "2026-11-10" }), null);
  assert.equal(noNewerText(view.note, { ...view.barrel, state: "withheld", date: null }), null);
  const current = fixture("fuels-view.json");
  assert.equal(current.note.observation_date, current.barrel.date);
  assert.equal(noNewerText(current.note, current.barrel), null);  // only an earlier note
  assert.equal(noNewerText({ ...view.note, state: "unbound" }, view.barrel), null);
});

test("an earlier note without latest prices says why instead", () => {
  const note = { ...fixture("fuels-view-earlier.json").note, now: null,
    problem: "The latest prices are withheld: No data for brent." };
  assert.equal(refreshedText(note),
    "Prices have been refreshed since this note: The latest prices are withheld: No data for brent.");
});

test("an AI draft is never presented as the owner's view", () => {
  const unreviewed = { state: "unreviewed", reviewed_on: null };
  assert.equal(authorship("Claude (AI-drafted)", unreviewed), "AI-drafted, not reviewed by the owner");
  assert.equal(authorship("Claude (AI-drafted)", { state: "reviewed", reviewed_on: "2026-11-07" }),
    "Reviewed by the owner on 7 Nov 2026");
  assert.equal(authorship("Owner", unreviewed), "Written by the owner");
});

test("a note row carries what is known about its author without contradicting the hero", () => {
  const latest = { ...fixture("fuels-view.json").note, author: "Owner" };
  const row = { number: latest.number, review: latest.review };
  assert.equal(noteRowLine(row, latest), "Written by the owner");
  assert.equal(noteRowLine(row, fixture("fuels-view.json").note), "AI-drafted, not reviewed by the owner");
  const older = { number: 7, review: { state: "unreviewed", reviewed_on: null } };
  assert.equal(noteRowLine(older, latest), "Not marked reviewed");
  assert.equal(noteRowLine({ number: 7, review: { state: "reviewed", reviewed_on: "2026-11-07" } }, latest),
    "Reviewed by the owner on 7 Nov 2026");
});

test("a publication date reads as published, or plainly as not given by EIA, whose API gives none", () => {
  assert.equal(publishedText("2026-11-04"), "published 4 Nov 2026");
  assert.equal(publishedText(null), "publication date not given by EIA");
  assert.equal(publishedText("2026-11-04", false), "4 Nov 2026");
  assert.equal(publishedText(null, false), "not given by EIA");
  // The captured replies come from EIA-shaped snapshots: no publication date anywhere.
  const view = fixture("fuels-view.json");
  assert.equal(view.barrel.published_on, null);
  assert.ok(view.series.every((row: { latest: { published_on: string | null } }) => row.latest.published_on === null));
});

test("an analysis is shown only filled and placed: every section, kind and source, and never with a raw placeholder", () => {
  const view = fixture("fuels-view-analysis.json");
  const placed = prose(view.note);
  assert.ok(placed && placed.analysis, "the captured analysis reads");
  assert.equal(view.note.note_version, "fuels-note-0.2");
  for (const [key] of ANALYSIS_SECTIONS) assert.ok(placed.analysis[key].length > 0, key);
  const items = ANALYSIS_SECTIONS.flatMap(([key]) => placed.analysis![key]);
  assert.ok(items.every((item) => (ANALYSIS_KINDS as readonly string[]).includes(item.kind) && !item.text.includes("{")));
  assert.ok(items.every((item) => item.sources.every((ref) => ref >= 0 && ref < placed.sources.length)));
  const words = placed.lede.split(/\s+/).filter(Boolean).length;
  assert.ok(words >= 40 && words <= 70, String(words));
  assert.equal(prose({ ...view.note, state: "unbound" }), null);
  const raw = structuredClone(view.note);
  raw.analysis.watch[0].text = "Still {week_from} here";
  assert.equal(prose(raw), null, "a placeholder left in the analysis hides the whole note");
  const unknown = structuredClone(view.note);
  unknown.analysis.meaning[0].kind = "forecast";
  assert.equal(prose(unknown), null);
});
