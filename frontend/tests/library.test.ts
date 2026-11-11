// The case library client: version-checked reads, publication times shown in the publisher's own offset (or as a
// stated date only), and browsing by search, topic and sector.
import assert from "node:assert/strict";
import test from "node:test";
import { fetchLibrary, fetchLibraryCase } from "../src/api.ts";
import {
  LIBRARY_CATEGORIES, LIBRARY_VIEW_VERSION, categoryCounts, filterCases, filtersHref, formatDay, latestPerCategory,
  publishedDay, publishedLocal, readFilters, sectorCounts, sectorLabel, unknownSector,
  type LibraryRow, type LibrarySector,
} from "../src/library.ts";

async function withFetch<T>(fake: typeof fetch, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = fake;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

const reply = (status: number, body: unknown, sent: { url: string; init?: RequestInit }[] = []) =>
  (async (url: string, init?: RequestInit) => {
    sent.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;

/** The zone this process started in. Deleting TZ does not make Node resolve its zone again, so it is set back by name. */
const STARTING_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
const STARTING_TZ = process.env.TZ;
const ZONES = ["UTC", "America/New_York", "Asia/Jerusalem", "Asia/Tokyo", "Pacific/Kiritimati", "Pacific/Pago_Pago"];

/** Runs `body` with this process's time zone set to `zone`, then restores both the zone and the TZ variable. */
function inZone<T>(zone: string, body: () => T): T {
  const original = process.env.TZ;
  process.env.TZ = zone;
  try {
    return body();
  } finally {
    process.env.TZ = original ?? STARTING_ZONE;  // Setting TZ makes Node resolve the zone again.
    if (original === undefined) delete process.env.TZ;  // Deleting does not, so the starting zone stays in force.
  }
}

test("the library and its cases are read with plain GETs and their view version is checked", async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  const signal = new AbortController().signal;
  const index = { view_version: LIBRARY_VIEW_VERSION, title: "Case library", cases: [] };
  assert.deepEqual(await withFetch(reply(200, index, sent), () => fetchLibrary(signal)), { state: "ready", data: index });
  const view = { view_version: LIBRARY_VIEW_VERSION, case: { id: "fomc-2025-03-19" } };
  assert.equal((await withFetch(reply(200, view, sent), () => fetchLibraryCase("fomc 2025", signal))).state, "ready");
  assert.deepEqual(sent.map(({ url, init }) => [url, init?.method ?? "GET"]),
                   [["/api/case-library", "GET"], ["/api/case-library/fomc%202025", "GET"]]);
  const foreign = await withFetch(reply(200, { ...index, view_version: "dossier-view-0.3" }), () => fetchLibrary(signal));
  assert.equal(foreign.state, "error");
  const missing = await withFetch(reply(404, { detail: "Unknown case" }), () => fetchLibraryCase("x", signal));
  assert.deepEqual(missing, { state: "missing", message: "Unknown case" });
  assert.equal((await withFetch(reply(500, { detail: "invalid" }), () => fetchLibrary(signal))).state, "error");
});

test("publication times are shown in the publisher's stated offset, whatever the reader's time zone", () => {
  // The override must take effect, or this test would only ever exercise one zone.
  const local = ZONES.map((zone) => inZone(zone, () => new Date("2025-07-03T12:00").toISOString()));
  assert.equal(new Set(local).size, ZONES.length, local.join(", "));
  for (const zone of ZONES) {
    inZone(zone, () => {
      assert.deepEqual(publishedLocal("2025-03-19T14:00:00-04:00"),
                       { day: "19 Mar 2025", clock: "14:00", offset: "UTC−04:00", utc: "18:00 UTC" }, zone);
      // Late in the publisher's evening the UTC date has already moved on; the publisher's date is kept.
      assert.deepEqual(publishedLocal("2025-07-15T23:30:00-04:00"),
                       { day: "15 Jul 2025", clock: "23:30", offset: "UTC−04:00", utc: "03:30 UTC" }, zone);
      // Wall-clock times that do not exist in New York (9 Mar 2025) or Jerusalem (28 Mar 2025), where clocks jumped
      // from 02:00 to 03:00: a stated offset makes them valid instants, and a reader's zone must never move them.
      assert.deepEqual(publishedLocal("2025-03-09T02:30:00-05:00"),
                       { day: "9 Mar 2025", clock: "02:30", offset: "UTC−05:00", utc: "07:30 UTC" }, zone);
      assert.deepEqual(publishedLocal("2025-03-28T02:30:00+02:00"),
                       { day: "28 Mar 2025", clock: "02:30", offset: "UTC+02:00", utc: "00:30 UTC" }, zone);
    });
  }
  // Restored: later tests in this file run in the zone the process started in, with TZ as it was.
  assert.equal(Intl.DateTimeFormat().resolvedOptions().timeZone, STARTING_ZONE);
  assert.equal(process.env.TZ, STARTING_TZ);
  assert.deepEqual(publishedLocal("2025-07-03T08:30:00+00:00")?.offset, "UTC+00:00");
  for (const bad of ["2025-03-19T14:00:00Z", "2025-03-19T14:00:00", "19 March 2025", "2025-02-30T14:00:00-04:00"]) {
    assert.equal(publishedLocal(bad), null, bad);
  }
});

const row = (id: string, category: string, published: string, title: string, summary: string,
             publisher = "U.S. Bureau of Labor Statistics", sectors: string[] = []): LibraryRow => {
  const timed = published.includes("T");
  return { id, category, published_at: published, title, summary, publisher, published_as_stated: "", sectors,
           publication: { precision: timed ? "time" : "date", date: published.slice(0, 10), at: published },
           market_context: false };
};
const ROWS: LibraryRow[] = [
  row("cpi-2025-05-13", "Inflation", "2025-05-13T08:30:00-04:00", "April 2025 CPI: 0.2% on the month",
      "Shelter accounted for more than half the rise."),
  row("fomc-2025-01-29", "Monetary policy", "2025-01-29T14:00:00-05:00", "The Fed holds after December's cut",
      "The statement dropped its inflation-progress line.", "Board of Governors of the Federal Reserve System"),
  row("empsit-2025-05-02", "Employment", "2025-05-02T08:30:00-04:00", "April 2025 jobs: payrolls +177,000",
      "Unemployment held at 4.2 percent and March was revised down."),
  row("cpi-2025-04-10", "Inflation", "2025-04-10T08:30:00-04:00", "March 2025 CPI: prices fall 0.1%",
      "Gasoline fell 6.3 percent after seasonal adjustment."),
];
const ids = (rows: LibraryRow[]) => rows.map((item) => item.id);

const SECTORS: LibrarySector[] = [
  { slug: "energy", label: "Energy", coverage: "c", selection: "s" },
  { slug: "manufacturing-automotive", label: "Manufacturing & automotive", coverage: "c", selection: "s" },
  { slug: "banking-credit", label: "Banking & credit", coverage: "c", selection: "s" },
];
const SLUGS = SECTORS.map((item) => item.slug);
// SYNTHETIC sector rows: date-only publications, one case in two sectors, and two cases on one date.
const SECTOR_ROWS: LibraryRow[] = [
  row("h8-2026-09-18", "Bank balance sheets", "2026-09-18", "Deposits up in the week", "Cash rose too.",
      "Board of Governors of the Federal Reserve System", ["banking-credit"]),
  row("g17-2026-09-18", "Industrial production", "2026-09-18", "August output flat", "Utilities up 1.8 percent.",
      "Board of Governors of the Federal Reserve System", ["manufacturing-automotive", "energy"]),
  row("eia-tie-2026-09-30", "Energy analysis", "2026-09-30", "EV electricity use grows 8%", "Sales fell after credits.",
      "U.S. Energy Information Administration", ["energy", "manufacturing-automotive"]),
  row("timed-2026-09-18", "Monetary policy", "2026-09-18T14:00:00-04:00", "A timed release", "Stated at 2 p.m.",
      "Board of Governors of the Federal Reserve System"),
];
const ALL = [...ROWS, ...SECTOR_ROWS];
const none = { query: "", category: null, sector: null };

test("library filters are read from the address; an unknown topic or sector means all", () => {
  assert.deepEqual(readFilters(""), none);
  assert.deepEqual(readFilters("?q=April%20payrolls&category=employment"),
                   { query: "April payrolls", category: "employment", sector: null });
  assert.deepEqual(readFilters("?category=astrology"), none);
  assert.deepEqual(readFilters("?sector=energy", SLUGS), { ...none, sector: "energy" });
  assert.deepEqual(readFilters("?sector=energy"), none);  // Without the collection's sectors, nothing is assumed.
  assert.deepEqual(readFilters("?sector=astrology", SLUGS), none);
  assert.equal(unknownSector("?sector=astrology", SLUGS), "astrology");
  assert.equal(unknownSector("?sector=energy", SLUGS), null);
  assert.equal(unknownSector("", SLUGS), null);
  assert.doesNotThrow(() => readFilters("?q=%E0%A4&category=%FF&sector=%FF", SLUGS));  // A malformed address never throws.
  assert.equal(readFilters("?q=%E0%A4&category=%FF").category, null);
  // The macro topics keep their place; the sector releases add topics of their own, separate from sectors.
  assert.deepEqual(LIBRARY_CATEGORIES.map((item) => item.label),
                   ["Monetary policy", "Employment", "Inflation", "Energy analysis", "Export controls",
                    "Industrial production", "Bank balance sheets", "International trade"]);
});

test("filters are written back to a stable address that reads back the same", () => {
  assert.equal(filtersHref(none), "/library");
  assert.equal(filtersHref({ query: "April payrolls", category: "employment", sector: null }),
               "/library?q=April+payrolls&category=employment");
  assert.equal(filtersHref({ query: "   ", category: "inflation", sector: null }), "/library?category=inflation");
  assert.equal(filtersHref({ sector: "banking-credit" }), "/library?sector=banking-credit");
  for (const filters of [{ query: "Fed & 4-1/4%", category: "monetary-policy", sector: null },
                         { query: "shelter", category: null, sector: null },
                         { query: "output", category: "industrial-production", sector: "energy" }]) {
    assert.deepEqual(readFilters(filtersHref(filters).slice("/library".length), SLUGS), filters);
  }
});

test("cases are ordered by publication date, a stated time first on a shared date, whatever order they arrive in", () => {
  const expected = ["fomc-2025-01-29", "cpi-2025-04-10", "empsit-2025-05-02", "cpi-2025-05-13", "timed-2026-09-18",
                    "g17-2026-09-18", "h8-2026-09-18", "eia-tie-2026-09-30"];
  assert.deepEqual(ids(filterCases(ALL, none)), expected);
  assert.deepEqual(ids(filterCases([...ALL].reverse(), none)), expected);
});

test("a case in two sectors is one record, listed under each sector and counted once in all", () => {
  assert.deepEqual(ids(filterCases(ALL, { ...none, sector: "energy" })), ["g17-2026-09-18", "eia-tie-2026-09-30"]);
  assert.deepEqual(ids(filterCases(ALL, { ...none, sector: "manufacturing-automotive" })),
                   ["g17-2026-09-18", "eia-tie-2026-09-30"]);
  assert.deepEqual(ids(filterCases(ALL, { ...none, sector: "banking-credit" })), ["h8-2026-09-18"]);
  const shown = ids(filterCases(ALL, none));
  assert.equal(shown.length, new Set(shown).size);  // No duplicate entries in the unfiltered list.
  assert.deepEqual(sectorCounts(ALL, SECTORS, ""),
                   { all: 8, energy: 2, "manufacturing-automotive": 2, "banking-credit": 1 });
  // Topic and sector combine; each control's count says what it would show with the other choices kept.
  assert.deepEqual(sectorCounts(ALL, SECTORS, "", "industrial-production"),
                   { all: 1, energy: 1, "manufacturing-automotive": 1, "banking-credit": 0 });
  assert.equal(categoryCounts(ALL, "", "energy")["energy-analysis"], 1);
  assert.equal(categoryCounts(ALL, "", "energy").all, 2);
  assert.deepEqual(ids(filterCases(ALL, { query: "", category: "inflation", sector: "energy" })), []);  // Honest empty.
  assert.equal(sectorLabel(SECTORS, "banking-credit"), "Banking & credit");
  assert.equal(sectorLabel(SECTORS, "unknown"), "unknown");
});

test("a date-only publication is shown as its stated date, never with a time, in any reader's time zone", () => {
  for (const zone of ZONES) {
    inZone(zone, () => {
      assert.equal(publishedDay({ precision: "date", date: "2026-09-18", at: "2026-09-18" }), "18 Sep 2026", zone);
      assert.equal(publishedDay({ precision: "time", date: "2025-07-15", at: "2025-07-15T23:30:00-04:00" }),
                   "15 Jul 2025", zone);
    });
  }
  for (const bad of ["2026-02-30", "18 September 2026", "2026-09-18T00:00:00-04:00"]) {
    assert.equal(formatDay(bad), null, bad);
  }
});

test("search is case-insensitive, needs every word, and covers titles, summaries, categories and publishers", () => {
  const search = (query: string, category: string | null = null) =>
    ids(filterCases(ROWS, { query, category, sector: null }));
  assert.deepEqual(search("APRIL"), ["empsit-2025-05-02", "cpi-2025-05-13"]);  // Titles, in date order.
  assert.deepEqual(search("april shelter"), ["cpi-2025-05-13"]);  // Every word must match somewhere in the case.
  assert.deepEqual(search("seasonal adjustment"), ["cpi-2025-04-10"]);  // Summary.
  assert.deepEqual(search("monetary"), ["fomc-2025-01-29"]);  // Category.
  assert.deepEqual(search("federal reserve"), ["fomc-2025-01-29"]);  // Publisher.
  assert.deepEqual(search("  bureau   OF labor "), ["cpi-2025-04-10", "empsit-2025-05-02", "cpi-2025-05-13"]);
  assert.deepEqual(search("april", "inflation"), ["cpi-2025-05-13"]);  // Combined with a category.
  assert.deepEqual(search("unicorn"), []);
  assert.deepEqual(search("", "employment"), ["empsit-2025-05-02"]);
});

test("category counts follow the search, so each control says how many cases it would show", () => {
  const sectorTopics = { "energy-analysis": 0, "export-controls": 0, "industrial-production": 0, "bank-balance-sheets": 0,
                         "international-trade": 0 };
  assert.deepEqual(categoryCounts(ROWS, ""), { all: 4, "monetary-policy": 1, employment: 1, inflation: 2, ...sectorTopics });
  assert.deepEqual(categoryCounts(ROWS, "april"),
                   { all: 2, "monetary-policy": 0, employment: 1, inflation: 1, ...sectorTopics });
});

test("the Tracker's compact view shows the latest case in each category, in publication order", () => {
  assert.deepEqual(ids(latestPerCategory(ROWS)), ["fomc-2025-01-29", "empsit-2025-05-02", "cpi-2025-05-13"]);
  assert.deepEqual(ids(latestPerCategory([...ROWS].reverse())), ["fomc-2025-01-29", "empsit-2025-05-02", "cpi-2025-05-13"]);
});
