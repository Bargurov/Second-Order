// What the Client says about current news, interests, searches, imports and limits (docs/news-usage-contract.md),
// built from server payloads only. A feed entry is discovery metadata, never a publication: nothing here turns an
// excerpt into a source. A publication time is the feed's own statement and is never replaced by a retrieval time; a
// time the feed does not state stays unknown. Filtering what is already shown sends nothing; only a deliberate search
// is sent, and it is counted by the server.
import {
  INTERESTS, SEARCH_RULES, newRequestKey, type Interest, type Interests, type Limits, type NewsEntry, type NewsSource,
  type NewsSourceKey, type Published, type QuotaNow, type SearchForm,
} from "../contracts/news.ts";
import type { SourceFields } from "./recovery.ts";
import { dayLabel, inUtc, inZone } from "./time.ts";

const thousands = (count: number) => count.toLocaleString("en-US");
const plural = (count: number, one: string, many: string) => `${thousands(count)} ${count === 1 ? one : many}`;

// ---------------------------------------------------------------- times

/** An entry's publication time as the feed states it, and why it is incomplete when it is. */
export function publishedText(published: Published, zone: string): { line: string; note: string | null } {
  if (published.state === "stated") {
    return { line: `Published ${inZone(published.utc!, zone)}`,
             note: published.note ?? (published.as_stated ? `The feed states “${published.as_stated}”.` : null) };
  }
  if (published.state === "date_only") {
    return { line: `Published ${dayLabel(published.date!)}; the feed states no time of day`, note: published.note };
  }
  return { line: "Publication time unknown: the feed's timestamp cannot be used",
           note: published.note ?? (published.as_stated ? `The feed states “${published.as_stated}”.` : null) };
}

/** When this server retrieved the entry: never its publication time. */
export function retrievedText(entry: NewsEntry, zone: string): string {
  if (entry.listing === "retained") {
    return `No longer in the feed; last retrieved ${inZone(entry.last_retrieved_at, zone)}`;
  }
  return entry.first_retrieved_at === entry.last_retrieved_at
    ? `Retrieved ${inZone(entry.last_retrieved_at, zone)}`
    : `First retrieved ${inZone(entry.first_retrieved_at, zone)}, last ${inZone(entry.last_retrieved_at, zone)}`;
}

// ---------------------------------------------------------------- sources

export type SourceTone = "ok" | "stale" | "missing";

/** A source's state as the server reports it: retrieved, stale after a failed attempt, or not retrieved and why. */
export function sourceStateText(source: NewsSource, zone: string): { tone: SourceTone; text: string } {
  const attempt = source.last_attempt;
  const said = (detail: string | null) => (detail ? `: ${detail.replace(/\.$/, "")}` : "");
  const held = `${plural(source.entries, "entry", "entries")} held`;
  let shown: { tone: SourceTone; text: string };
  if (source.stale && source.last_success_at) {
    const last = attempt ? `The last retrieval, at ${inZone(attempt.at, zone)}, ${attempt.outcome === "not_requested"
      ? "was not requested" : "failed"}${said(attempt.detail)}.` : "The last retrieval did not succeed.";
    shown = { tone: "stale", text: `${last} The entries shown are from ${inZone(source.last_success_at, zone)} (${held}).` };
  } else if (source.state === "ok" && source.last_success_at) {
    shown = { tone: "ok", text: `Retrieved ${inZone(source.last_success_at, zone)} · ${held}` };
  } else if (source.state === "not_requested") {
    shown = { tone: "missing", text: attempt?.detail ?? "Not requested on this server." };
  } else if (source.state === "failed") {
    shown = { tone: "missing", text: attempt ? `Not retrieved: the attempt at ${inZone(attempt.at, zone)} failed${
      said(attempt.detail)}.` : "Not retrieved: the last attempt failed." };
  } else if (source.state === "unreadable") {
    shown = { tone: "missing", text: "This server's saved retrieval could not be read, so nothing from it is shown." };
  } else {
    shown = { tone: "missing", text: "Not retrieved yet. An administrator refreshes the official feeds; reading this " +
      "page requests nothing from a publisher." };
  }
  return source.note ? { ...shown, text: `${shown.text} ${source.note}` } : shown;
}

/** The publishers this view covers, by name, and a plain statement that nothing else is. */
export function coverageText(sources: NewsSource[]): string {
  const publishers = [...new Set(sources.map((source) => source.publisher))];
  const named = publishers.length > 1 ? `${publishers.slice(0, -1).join(", ")} and ${publishers.at(-1)}` : publishers.join("");
  return `This page covers ${plural(sources.length, "official feed", "official feeds")} from ${named} only. It is not ` +
    "all news.";
}

// ---------------------------------------------------------------- filter (free: nothing is sent)

export interface NewsFilter { interest: Interest | null; source: NewsSourceKey | null; retained: boolean }

export const NO_FILTER: NewsFilter = { interest: null, source: null, retained: true };

/** The entries shown under a filter of what was already read: by interest, by source, current or also retained. */
export function filtered(entries: NewsEntry[], filter: NewsFilter): NewsEntry[] {
  return entries.filter((entry) => (filter.interest === null || entry.topics.some((topic) => topic.interest === filter.interest)) &&
    (filter.source === null || entry.source === filter.source) && (filter.retained || entry.listing === "current"));
}

// ---------------------------------------------------------------- interests

/** The interests to send: the vocabulary's order, each once. */
export function selection(interests: Interests, chosen: ReadonlySet<Interest>): Interest[] {
  const order = interests.vocabulary.map((row) => row.interest);
  return INTERESTS.filter((slug) => chosen.has(slug)).sort((a, b) => order.indexOf(a) - order.indexOf(b));
}

export const sameSelection = (a: Interest[], b: Interest[]): boolean => a.length === b.length && a.every((slug, index) => slug === b[index]);

// ---------------------------------------------------------------- search (counted by the server)

/** The words of a query as the server counts them: runs of letters and digits after NFKC normalisation. */
export const queryWords = (query: string): string[] => query.normalize("NFKC").toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];

/** A query the server would certainly refuse, said before anything is sent (and so before anything is counted). */
export function searchProblem(query: string): string | null {
  const typed = query.trim();
  if (typed === "") return "Type at least one word to search for.";
  if (Array.from(typed).length > SEARCH_RULES.maxCharacters) {
    return `A search has at most ${SEARCH_RULES.maxCharacters} characters.`;
  }
  const words = queryWords(typed).length;
  if (words === 0) return "A search needs at least one word of letters or digits.";
  if (words > SEARCH_RULES.maxWords) return `A search has at most ${SEARCH_RULES.maxWords} words; this one has ${words}.`;
  return null;
}

export type SearchBody = Omit<SearchForm, "request_key">;

/** The last search sent from this page: its body, its key, and whether its reply was confirmed. */
export interface SentSearch { body: SearchBody; key: string; confirmed: boolean }

/** The key for a deliberate search. Pressing Search again after a reply that never arrived repeats the same key for the
 * same body, so the server answers it as the same search and never counts it twice; anything else is a new search. */
export function searchKey(previous: SentSearch | null, body: SearchBody, fresh: () => string = newRequestKey): string {
  return previous && !previous.confirmed && JSON.stringify(previous.body) === JSON.stringify(body) ? previous.key : fresh();
}

// ---------------------------------------------------------------- paste instead of import

export interface PasteOffer {
  entryId: string; publisher: string; title: string; link: string; fields: SourceFields; notes: string[];
}

/** The paste step's form filled from an entry: its headline, its official address and only the publication time the
 * feed states. The text is left for the person to paste from the publication: an excerpt is not the publication. */
export function pasteOffer(entry: NewsEntry, publisher: string): PasteOffer {
  const notes = ["Paste the publication's own text from its official page. The feed's excerpt is not the publication " +
    "and is not filled in."];
  if (entry.title_shortened) notes.push("The feed shortened this headline; check it against the publication.");
  const fields: SourceFields = { headline: entry.title, source_url: entry.link, date: "", time: "", offset: "", text: "" };
  const published = entry.published;
  if (published.state === "stated" && published.utc) {
    const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}):(\d{2})(?:\.\d+)?(?:Z|\+00:00)$/.exec(published.utc);
    if (match && match[3] === "00") {
      Object.assign(fields, { date: match[1], time: match[2], offset: "+00:00" });
      notes.push("The publication time is the feed's, in UTC (UTC+00:00); check it against the publication.");
    } else {
      notes.push("Type the publication time from the official page.");
    }
  } else if (published.state === "date_only" && published.date) {
    fields.date = published.date;
    notes.push("The feed states only the date; type the time of day and its UTC offset from the official page.");
  } else {
    notes.push("The feed's publication time cannot be used; type the date, the time and its UTC offset from the " +
      "official page.");
  }
  return { entryId: entry.entry_id, publisher, title: entry.title, link: entry.link, fields, notes };
}

let offered: PasteOffer | null = null;

/** Hand an entry's paste step to the new-source page, in this tab's memory only, once. */
export function offerPaste(offer: PasteOffer): void {
  offered = offer;
}

/** The paste step offered from the news, if any. */
export const peekPaste = (): PasteOffer | null => offered;

/** The new-source page has taken the offer (or the person left it): it is not offered again. */
export function clearPaste(): void {
  offered = null;
}

// ---------------------------------------------------------------- limits

/** One counted operation's figures as the server holds them. */
export function quotaText(quota: QuotaNow): string {
  if (quota.limit === null) return `${quota.label}: none allowed until the administrator sets limits`;
  return `${quota.label}: ${thousands(quota.used)} of ${thousands(quota.limit)} used today · ${thousands(quota.remaining ?? 0)} left`;
}

/** What the account holds against its storage limits. */
export function storageText(limits: Limits): string[] {
  const { sources, source_bytes: bytes } = limits.storage;
  return [
    sources.limit === null ? `Sources held: ${thousands(sources.used)}` : `Sources held: ${thousands(sources.used)} of ${thousands(sources.limit)}`,
    bytes.limit === null ? `Source text held: ${thousands(bytes.used)} bytes`
      : `Source text held: ${thousands(bytes.used)} of ${thousands(bytes.limit)} bytes`,
  ];
}

/** When today's counts reset, in the server's quota time zone and in UTC. */
export const resetText = (limits: Limits): string =>
  `Counts reset ${inZone(limits.resets_at, limits.timezone)} (${inUtc(limits.resets_at)}).`;
