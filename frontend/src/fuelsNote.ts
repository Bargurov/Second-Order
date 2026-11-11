// The fuels page's situation-note wording: which note prose may be shown, how an earlier note is compared with the
// latest prices, who stands behind a note, and how a publication date reads. Pure functions
// over the checked reply (fuels.ts); nothing here computes a price.
import { isRec } from "./copperTools.ts";
import { formatDay } from "./format.ts";
import { isText, type BarrelView, type FuelsView, type NoteView } from "./fuels.ts";
import { money } from "./fuelsText.ts";

export const DRIVERS = [["supply", "Supply"], ["demand", "Demand"], ["stocks", "Stocks"]] as const;
/** A fuels-note-0.2's four questions, in their order. */
export const ANALYSIS_SECTIONS = [["what_happened", "What happened"], ["meaning", "What it may mean"],
  ["relevance", "Who it may touch"], ["watch", "What to check next"]] as const;
export const ANALYSIS_KINDS = ["observation", "computed", "hypothesis", "sourced", "source_projection"] as const;
export type AnalysisKind = (typeof ANALYSIS_KINDS)[number];
export interface AnalysisItem {
  kind: AnalysisKind; text: string; sources: number[]; mechanism: string | null; mechanism_title: string | null;
}
export type Analysis = Record<(typeof ANALYSIS_SECTIONS)[number][0], AnalysisItem[]> & { caveats: string[] };
/** The analysis' fixed words. */
export const ANALYSIS_COPY = {
  summary: "Read the analysis",
  summaryEarlier: "Read the earlier analysis",
  region: "Analysis of these prices",
  caveatsHead: "What this cannot tell",
  sourcesHead: "Sources of this analysis",
  source: "Source",
  mechanism: "Mechanism on this page:",
  kinds: { observation: "Observation", computed: "Computed", hypothesis: "Possible explanation",
    sourced: "Sourced claim", source_projection: "Projection, attributed" } as Record<AnalysisKind, string>,
  titles: {
    observation: "Observation: a price as EIA published it, in the snapshot this analysis was written for",
    computed: "Computed by fixed code from the verified prices of that snapshot",
    hypothesis: "Possible explanation: a reading or a general mechanism, not a finding about this move",
    sourced: "Sourced claim: what the cited source says, attributed to it",
    source_projection: "Projection attributed to its source: the source's view of the future, not this page's",
  } as Record<AnalysisKind, string>,
  legend: "Every figure, date and direction above is filled by code from the snapshot this analysis was written "
    + "for. An observation is a price as EIA published it; a computed figure comes from fixed code; a possible "
    + "explanation is a reading or a general mechanism, not a finding; a sourced claim or a projection is the cited "
    + "source's, not this page's.",
};

interface NoteSource { title: string; publisher: string; date: string; url: string; locator: string }
export interface Prose {
  headline: string; lede: string; written_on: string; covers_through: string; observation_date: string;
  author: string; review: unknown; sources: NoteSource[];
  /** fuels-note-0.1: three columns. */
  columns?: Record<(typeof DRIVERS)[number][0], string>;
  /** fuels-note-0.2: the analysis in their place, the lede being its visible summary. */
  analysis?: Analysis;
}
type NoteRow = Pick<FuelsView["notes"][number], "number" | "review">;

/** A note's filled prose, only when it is placed beside these prices (current or earlier) and fully shaped. An unbound
 * note's prose still holds its raw {placeholders} and is never returned, so it is never shown as a current reading. */
export function prose(note: NoteView): Prose | null {
  if (note.state !== "current" && note.state !== "earlier") return null;
  if (isRec(note.analysis)) return analysed(note);
  const columns = note.columns;
  const texts = [note.headline, note.lede, note.written_on, note.covers_through, note.observation_date,
    ...(isRec(columns) ? DRIVERS.map(([key]) => columns[key]) : [null])];
  if (!texts.every(isText) || texts.some((text) => text.includes("{"))) return null;
  return note as unknown as Prose;
}

/** A fuels-note-0.2's prose, when every text is filled and every statement has a listed kind. */
function analysed(note: NoteView): Prose | null {
  const analysis = note.analysis as Record<string, unknown>;
  const items = ANALYSIS_SECTIONS.flatMap(([key]) => (Array.isArray(analysis[key]) ? analysis[key] as unknown[] : [null]));
  const caveats = Array.isArray(analysis.caveats) ? analysis.caveats as unknown[] : [null];
  if (!items.every((item) => isRec(item) && (ANALYSIS_KINDS as readonly string[]).includes(item.kind as string)
      && Array.isArray(item.sources))) return null;
  const texts = [note.headline, note.lede, note.written_on, note.covers_through, note.observation_date,
    ...items.map((item) => (item as AnalysisItem).text), ...caveats];
  if (!texts.every(isText) || texts.some((text) => text.includes("{"))) return null;
  return note as unknown as Prose;
}

/** The line under an earlier note: the then-and-now prices, or why the latest prices are not shown. */
export function refreshedText(note: NoteView): string {
  const { then, now } = note;
  if (then && now) {
    return `Prices have been refreshed since this note: Brent then ${money(then.brent)}, now ${money(now.brent)}; `
      + `crack then ${money(then.crack)}, now ${money(now.crack)}.`;
  }
  return `Prices have been refreshed since this note: ${note.problem ?? "the latest prices are not available."}`;
}

/** After a refresh that brought no newer observation (an earlier note written for the latest barrel's date), the one
 * sentence added after the then-and-now line; otherwise null. It speaks of what the refresh found, not of what EIA
 * published when. */
export function noNewerText(note: NoteView, barrel: Pick<BarrelView, "date">): string | null {
  if (note.state !== "earlier" || !isText(barrel.date) || note.observation_date !== barrel.date) return null;
  return `The latest refresh found no observation newer than ${formatDay(barrel.date)}.`;
}

const reviewedOn = (review: unknown): string | null =>
  (isRec(review) && review.state === "reviewed" && isText(review.reviewed_on) ? review.reviewed_on : null);

/** Who stands behind a note: an AI draft is never presented as the owner's view. */
export function authorship(author: unknown, review: unknown): string {
  if (author === "Owner") return "Written by the owner";
  const day = reviewedOn(review);
  return day ? `Reviewed by the owner on ${formatDay(day)}` : "AI-drafted, not reviewed by the owner";
}

/** A row of the notes list. The rows carry no author: the latest note's row borrows the latest note's author, so it
 * reads as the hero does; an older row states only its committed review state. */
export function noteRowLine(row: NoteRow, latest: NoteView): string {
  if (latest.number === row.number && isText(latest.author)) return authorship(latest.author, row.review);
  const day = reviewedOn(row.review);
  return day ? `Reviewed by the owner on ${formatDay(day)}` : "Not marked reviewed";
}

/** "published 4 Nov 2026", or plainly that EIA gives no publication date (its API gives none; none is inferred). */
export function publishedText(day: string | null, withWord = true): string {
  if (day === null) return withWord ? "publication date not given by EIA" : "not given by EIA";
  return withWord ? `published ${formatDay(day)}` : formatDay(day);
}
