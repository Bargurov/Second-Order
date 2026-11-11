// The case library: committed, retrospective editorial cases served read-only by /api/case-library.
// They are not hypotheses and never reach the Tracker's research sections or any score.

export const LIBRARY_VIEW_VERSION = "case-library-view-0.3";

/**
 * How a case's source states its publication: "time" (a time with an explicit offset) or "date" (a calendar date
 * only, because the source states no time or no time zone; none is invented). `date` is the stated calendar date.
 */
export interface Publication {
  precision: "time" | "date";
  date: string;
  at: string;
}

export interface LibraryRow {
  id: string;
  title: string;
  category: string;
  summary: string;
  published_at: string;
  published_as_stated: string;
  publication: Publication;
  publisher: string;
  /** The slugs of the sectors the case covers: one case can be under several sectors, stored once. */
  sectors: string[];
  /** Whether the case is meant to show market context (the context itself is read and verified separately). */
  market_context: boolean;
}

/** A sector the collection declares: what its cases cover, and the rule that selected them. */
export interface LibrarySector {
  slug: string;
  label: string;
  coverage: string;
  selection: string;
}

export interface CaseLibraryIndex {
  view_version: string;
  title: string;
  introduction: string;
  labels: string[];
  selection: string;
  sectors: LibrarySector[];
  sector_membership: string | null;
  cases: LibraryRow[];
}

export interface LibrarySource {
  publisher: string;
  title: string;
  url: string;
  document_id: string | null;
  published_at: string;
  /** Absent on the twelve 0.1 cases, which always state a time. */
  published_precision?: "time" | "date";
  published_as_stated: string;
  timezone_note: string;
  reference_period: string;
  page_last_updated: string | null;
  retrieved_on: string;
  /** 0.3 entries: where the date comes from when the page states none, and the private copy they were written from. */
  date_basis?: string;
  retained?: { approval_id: string; sha256: string; bytes: number; retrieved_at: string; charset: string } | null;
}

export interface LibraryCase {
  id: string;
  title: string;
  category: string;
  summary: string;
  source: LibrarySource;
  overview: string[];
  key_facts: { label: string; value: string; basis: string }[];
  channels: { title: string; source_fact: string; interpretation: string }[];
  competing_explanations: { title: string; detail: string }[];
  assumptions: string[];
  missing_information: string[];
  weakening_observations: string[];
  critique: { title: string; detail: string }[];
  source_notes: { title: string; detail: string; url: string | null }[];
  /** Always null: no sourced expectations benchmark is used, so no case says whether a release surprised. */
  expectations_benchmark: null;
  /** 0.3 entries only. Meeting proceedings may list no channels: no market transmission is invented. */
  entry_kind?: "release" | "forecast" | "proceedings";
  provenance: {
    prepared_by: string;
    prepared_on: string;
    method: string;
    sources_read: string[];
    ai_assisted: true;
    retrospective: true;
    prepared_after_publication: true;
    human_review: "not_reviewed";
    research_use: "excluded";
  };
}

export interface LibraryCaseView {
  view_version: string;
  case: LibraryCase;
  position: number;
  count: number;
  previous: { id: string; title: string } | null;
  next: { id: string; title: string } | null;
  publication: Publication;
  sectors: { slug: string; label: string }[];
  market_context: boolean;
}

/**
 * The library's topics, in the order the topic controls show them; the slug is what the address carries. Topics say
 * what kind of release a case reads; sectors (declared by the collection) say what it covers. They are separate.
 */
export const LIBRARY_CATEGORIES = [
  { slug: "monetary-policy", label: "Monetary policy" },
  { slug: "employment", label: "Employment" },
  { slug: "inflation", label: "Inflation" },
  { slug: "energy-analysis", label: "Energy analysis" },
  { slug: "export-controls", label: "Export controls" },
  { slug: "industrial-production", label: "Industrial production" },
  { slug: "bank-balance-sheets", label: "Bank balance sheets" },
  { slug: "international-trade", label: "International trade" },
] as const;

/** The browsing state of /library, kept in its address: ?q=<search>&category=<slug>&sector=<slug>. */
export interface LibraryFilters {
  query: string;
  /** A category slug, or null for all categories. */
  category: string | null;
  /** A sector slug, or null for all sectors. */
  sector: string | null;
}

const MAX_QUERY = 200;
const SLUG = /^[a-z]+(?:-[a-z]+)*$/;
const slugOf = (label: string) => LIBRARY_CATEGORIES.find((item) => item.label === label)?.slug ?? null;

/**
 * Filters from an address's query string. An unknown category means all; a sector is kept only when it is one of
 * `sectors` (the collection's declared slugs), so an unknown one also means all. Nothing here can throw.
 */
export function readFilters(search: string, sectors: readonly string[] = []): LibraryFilters {
  const params = new URLSearchParams(search);
  const category = params.get("category");
  const sector = params.get("sector");
  return {
    query: (params.get("q") ?? "").slice(0, MAX_QUERY),
    category: LIBRARY_CATEGORIES.some((item) => item.slug === category) ? category : null,
    sector: sector && SLUG.test(sector) && sectors.includes(sector) ? sector : null,
  };
}

/** The sector an address asks for when the collection has no such sector, for an honest note; otherwise null. */
export function unknownSector(search: string, sectors: readonly string[]): string | null {
  const sector = new URLSearchParams(search).get("sector");
  return sector !== null && !sectors.includes(sector) ? sector.slice(0, 60) : null;
}

/** The address for a browsing state: empty parts are left out, so "/library" is the unfiltered library. */
export function filtersHref({ query, category, sector }: Partial<LibraryFilters>): string {
  const params = new URLSearchParams();
  if (query?.trim()) params.set("q", query);
  if (category) params.set("category", category);
  if (sector) params.set("sector", sector);
  const search = params.toString();
  return search ? `/library?${search}` : "/library";
}

const fold = (text: string) => text.toLocaleLowerCase("en-US");

/**
 * Every word of the search must appear in the case's title, summary, category or publisher. Case bodies are
 * deliberately not searched, so the control is never described as full-text search.
 */
function matches(row: LibraryRow, query: string): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  const haystack = fold([row.title, row.summary, row.category, row.publisher].join(" "));
  return words.every((word) => haystack.includes(word));
}

/**
 * One deterministic order everywhere, the server's: by stated publication date; on one date, cases with a stated
 * time first, by instant; then by case ID. A date-only case is never given a time.
 */
function orderKey(row: LibraryRow): [string, number, number, string] {
  const timed = row.publication.precision === "time";
  return [row.publication.date, timed ? 0 : 1, timed ? Date.parse(row.publication.at) : 0, row.id];
}

function byPublication(rows: LibraryRow[]): LibraryRow[] {
  return [...rows].sort((a, b) => {
    const [x, y] = [orderKey(a), orderKey(b)];
    return x[0].localeCompare(y[0]) || x[1] - y[1] || x[2] - y[2] || x[3].localeCompare(y[3]);
  });
}

const inCategory = (row: LibraryRow, category: string | null) => !category || slugOf(row.category) === category;
const inSector = (row: LibraryRow, sector: string | null) => !sector || row.sectors.includes(sector);

/** The cases that match the search, the topic and the sector together, in publication order. Each case once. */
export function filterCases(rows: LibraryRow[], { query, category, sector }: LibraryFilters): LibraryRow[] {
  return byPublication(rows).filter((row) => inCategory(row, category) && inSector(row, sector) && matches(row, query));
}

/** How many cases each topic control would show with the current search and sector, and how many all would. */
export function categoryCounts(rows: LibraryRow[], query: string, sector: string | null = null): Record<string, number> {
  const found = rows.filter((row) => inSector(row, sector) && matches(row, query));
  return Object.fromEntries([["all", found.length],
    ...LIBRARY_CATEGORIES.map((item) => [item.slug, found.filter((row) => row.category === item.label).length])]);
}

/**
 * How many cases each sector control would show with the current search and topic, and how many all would. A case
 * in two sectors counts once in each, and once in "all": the sector counts need not add up to the total.
 */
export function sectorCounts(rows: LibraryRow[], sectors: readonly LibrarySector[], query: string,
                             category: string | null = null): Record<string, number> {
  const found = rows.filter((row) => inCategory(row, category) && matches(row, query));
  return Object.fromEntries([["all", found.length],
    ...sectors.map((item) => [item.slug, found.filter((row) => row.sectors.includes(item.slug)).length])]);
}

/** The most recent case in each category, in publication order: the Tracker's compact view of the library. */
export function latestPerCategory(rows: LibraryRow[]): LibraryRow[] {
  const sorted = byPublication(rows);
  return sorted.filter((row) => sorted.filter((other) => other.category === row.category).at(-1) === row);
}

export const categorySlug = slugOf;

/** A sector slug's label, or the slug itself when the collection does not declare it. */
export const sectorLabel = (sectors: readonly LibrarySector[], slug: string) =>
  sectors.find((item) => item.slug === slug)?.label ?? slug;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const EXPLICIT = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})([+-])(\d{2}):(\d{2})$/;
const pad = (value: number) => String(value).padStart(2, "0");

/** "18 Sep 2026" for a YYYY-MM-DD date, or null for anything else. */
export function formatDay(day: string): string | null {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!parts) return null;
  const [year, month, date] = parts.slice(1).map(Number);
  const value = new Date(Date.UTC(year, month - 1, date));
  if (value.getUTCFullYear() !== year || value.getUTCMonth() !== month - 1 || value.getUTCDate() !== date) return null;
  return `${date} ${MONTHS[month - 1]} ${year}`;
}

/** The day a list shows for a case: from the stated time's own offset, or the stated date for a date-only source. */
export function publishedDay(publication: Publication): string | null {
  return publication.precision === "date" ? formatDay(publication.date) : publishedLocal(publication.at)?.day ?? null;
}

/**
 * A publication time read in the publisher's own stated offset: its calendar day and clock there, the offset, and
 * the UTC clock. The reader's time zone is never used. Anything without an explicit ±HH:MM offset, or an impossible
 * date, gives null rather than a guess.
 */
export function publishedLocal(iso: string): { day: string; clock: string; offset: string; utc: string } | null {
  const parts = EXPLICIT.exec(iso);
  if (!parts) return null;
  const [year, month, day, hour, minute] = parts.slice(1, 6).map(Number);
  const local = new Date(Date.UTC(year, month - 1, day, hour, minute));
  if (local.getUTCFullYear() !== year || local.getUTCMonth() !== month - 1 || local.getUTCDate() !== day ||
      hour > 23 || minute > 59) {
    return null;
  }
  const offsetMinutes = (Number(parts[8]) * 60 + Number(parts[9])) * (parts[7] === "-" ? -1 : 1);
  const utc = new Date(local.getTime() - offsetMinutes * 60_000);
  return {
    day: `${day} ${MONTHS[month - 1]} ${year}`,
    clock: `${parts[4]}:${parts[5]}`,
    offset: `UTC${parts[7] === "-" ? "−" : "+"}${parts[8]}:${parts[9]}`,
    utc: `${pad(utc.getUTCHours())}:${pad(utc.getUTCMinutes())} UTC`,
  };
}
