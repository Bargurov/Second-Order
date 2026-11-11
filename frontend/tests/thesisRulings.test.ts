// Rulings R15 to R18 of the copper thesis slice, read fail-closed against the captured SYNTHETIC replies:
// R15 an element cites at least one figure or passage; R16 edition_date orders editions and is never shown as a date;
// R17 a PDF names one of two truthful transcription methods; R18 the price record may be in US cents per pound, both
// figures in one unit, never converted.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { TRANSCRIPTION_METHODS, UNITS, figureText, thesisRefusal, transcriptionText, type Figure, type ThesisView }
  from "../src/thesis.ts";

const fixture = <T>(name: string): T => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const available = fixture<ThesisView>("thesis-available.json");
const SYNTHETIC = "synthetic-copper";
const TEXT_LAYER = "transcribed from the PDF's text layer";
const CENTS = "usd_cents_per_lb";

function refusalOf(change: (view: ThesisView) => void): string | null {
  const copy = structuredClone(available);
  change(copy);
  return thesisRefusal(copy, SYNTHETIC, null);
}
const pdf = (view: ThesisView) => view.sources.find((item) => item.id === "iea-2021")!;
const NOTHING = "cites no figure or passage, so nothing on it could be checked";

test("R15: an element that cites nothing is refused, whatever its kind or state", () => {
  // The final review's probe: a not_stated view citing nothing, consistent in every other field, read "available".
  const silent = refusalOf((view) => {
    view.view.statement = { status: "not_stated", text: "Synthetic: the sources do not state a view.", cites: [],
      figures: [], passages: [] };
    Object.assign(view.view, { items: [], sources: [] });
  });
  assert.equal(silent, `view.items: ${NOTHING}`);
  // One check for every kind, withheld or not: a withheld risk that lists nothing it was checked against.
  const unavailable = fixture<ThesisView>("thesis-unavailable.json");
  const risk = unavailable.risks.find((item) => item.id === "construction-slowdown")!;
  Object.assign(risk, { items: [], sources: [], problems: [] });
  assert.equal(thesisRefusal(unavailable, SYNTHETIC, null), `risks[construction-slowdown].items: ${NOTHING}`);
});

test("R16: the page shows an edition's own label and never its ordering date", () => {
  const footer = source("../src/pages/ThesisPage.tsx");
  const sections = source("../src/components/ThesisSections.tsx");
  assert.match(footer, /<dt>Edition<\/dt><dd>\{source\.edition\}<\/dd>/);
  assert.match(sections, /\{moved\.publisher\} \{moved\.edition\}<\/dd>/);
  for (const text of [footer, sections]) {
    assert.doesNotMatch(text, /dated \{|the edition of|edition_date/);
  }
});

test("R16: the edition date still orders editions in the reader", () => {
  const refusal = refusalOf((view) => {
    view.sources.find((item) => item.id === "iea-2025")!.edition_date = "2026-08-01";
  });
  assert.ok(refusal?.startsWith("reasons[clean-tech-demand].measure: "), String(refusal));
});

test("R17: exactly two transcription methods are read, and the footer prints the one used", () => {
  assert.deepEqual([...TRANSCRIPTION_METHODS], ["transcribed from the page image", TEXT_LAYER]);
  assert.equal(refusalOf(() => {}), null);
  assert.equal(refusalOf((view) => { pdf(view).transcription!.method = TEXT_LAYER; }), null);
  for (const method of ["transcribed", "Transcribed from the page image", "transcribed from the PDF text layer",
    "transcribed from the page image ", "read by a library", ""]) {
    const refusal = refusalOf((view) => { pdf(view).transcription!.method = method; });
    assert.ok(refusal?.startsWith("sources[iea-2021].transcription.method: "), `${method}: ${refusal}`);
  }
  const used = pdf(available);
  assert.equal(transcriptionText(used), "transcribed from the page image (pages 1, 2 of the PDF)");
  assert.equal(transcriptionText({ transcription: { pages: [3], method: TEXT_LAYER } }),
    "transcribed from the PDF's text layer (page 3 of the PDF)");
  assert.match(source("../src/pages/ThesisPage.tsx"), /transcriptionText\(source\)/);
});

/** The price record's two figures as copies in US cents per pound, under new ids (the originals stay in tonnes where
 * the computed exposure row uses one). */
function inCents(view: ThesisView, which: ("opening" | "latest")[]): void {
  const record = view.price_record;
  for (const key of which) {
    const id = `synthetic-cents-${key}`;
    const copy: Figure = { ...record[key]!, id, unit: CENTS };
    const index = record.items.findIndex((item) => item.id === record[key]!.id);
    record.items[index] = { ...record.items[index], id };
    record[key] = copy;
  }
}

test("R18: the price record may be in US cents per pound, in one unit", () => {
  assert.ok((UNITS as readonly string[]).includes(CENTS));
  assert.equal(available.labels.units[CENTS], "US cents per pound");
  assert.equal(refusalOf((view) => { inCents(view, ["opening", "latest"]); }), null);
  assert.match(figureText({ ...available.price_record.latest!, unit: CENTS }, { publisher: "P", edition: "E" }),
    /US cents per pound/);
  const mixed = refusalOf((view) => { inCents(view, ["opening"]); });
  assert.ok(mixed?.startsWith("price_record: "), String(mixed));
  assert.match(mixed!, /usd_cents_per_lb/);
  assert.match(mixed!, /usd_per_tonne/);
  const other = refusalOf((view) => {
    inCents(view, ["opening", "latest"]);
    view.price_record.opening!.unit = "usd_per_lb";
  });
  assert.ok(other?.startsWith("price_record.opening: "), String(other));
});

test("R18: a US cents per pound figure is not a per-unit cost price", () => {
  const refusal = refusalOf((view) => {
    const walk = (node: unknown): void => {
      if (Array.isArray(node)) node.forEach(walk);
      else if (typeof node === "object" && node !== null) {
        const record = node as Record<string, unknown>;
        if (record.id === "wb-copper-2026m10" && "as_shown" in record) record.unit = CENTS;
        Object.values(record).forEach(walk);
      }
    };
    walk(view);
  });
  assert.ok(refusal?.includes("expected a figure in usd_per_tonne"), String(refusal));
});
