// How the Client says what a story's payload states (src/contracts/stories.ts): times with their basis, coverage in
// words, a brief's provenance, and the honest state of a story without a brief. Nothing here decides anything: every
// fact is the server's, and a missing one is said to be missing.
import type { Interest } from "../contracts/news.ts";
import type { Account } from "../contracts/user.ts";
import type { AWAITING_STATES, Brief, BriefState, Coverage, CoverageCounts, Dimension, MaterialReport, Relevance,
  StoryCard, StoryPage, StorySource, TextState,
} from "../contracts/stories.ts";
import { AUTHORSHIP_OF } from "../contracts/stories.ts";
import type { EconomicsSummary, Figure } from "../contracts/economics.ts";
import { dayLabel, inZone } from "./time.ts";

/** What a quoted figure is, as the server states it: its period, nominal or real basis, seasonal adjustment, summary
 * statistic, stock or flow (an annual rate is never a month's count) and any margin its quote writes beside it. */
export function figureDetails(row: Pick<Figure, "period" | "basis_label" | "seasonal_label" | "statistic_label" |
  "stock_flow_label" | "margin">): string[] {
  return [row.period, row.basis_label, row.seasonal_label, row.statistic_label, row.stock_flow_label,
    row.margin ? `stated margin ${row.margin}` : null].filter((part): part is string => Boolean(part));
}

/** What the explanation says of its evidence: its form, a survey's respondents and its subject (0.4), or that an
 * earlier explanation did not record its form (classification_note); null when neither is given. */
export function evidenceLine(summary: Pick<EconomicsSummary, "instrument_label" | "form_label" | "respondents_label" |
  "classification_note">): { recorded: boolean; text: string } | null {
  if (summary.form_label) {
    const whose = summary.respondents_label ? ` (${summary.respondents_label})` : "";
    return { recorded: true, text: `Evidence: ${summary.form_label}${whose}. Subject: ${summary.instrument_label}.` };
  }
  return summary.classification_note ? { recorded: false, text: summary.classification_note } : null;
}

/** The interests' labels (news-interests-0.2, user_news.INTERESTS); tests/stories-view.test.ts holds them equal. */
export const INTEREST_LABEL: Record<Interest, string> = {
  "monetary-policy": "Monetary policy", employment: "Employment", inflation: "Inflation", energy: "Energy",
  trade: "Trade", markets: "Markets", technology: "Technology", companies: "Companies",
};

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

/** "First reported 14 Oct 2026, 12:00 (UTC)", saying when the feed states only a date (the time is then the end of that
 * date in UTC, or the first sighting, so only the date is shown) or when a time is only this server's first sighting. */
export function timeLine(at: string, basis: "published" | "dated" | "first_seen", zone: string, verb: string): string {
  if (basis === "published") return `${verb} ${inZone(at, zone)}`;
  if (basis === "dated") return `${verb} ${dayLabel(at.slice(0, 10))}: the feed states the date, not the time`;
  return `${verb} ${inZone(at, zone)}: first seen by this server; the feed states no time`;
}

export function storyTimes(story: Pick<StoryCard, "first_at" | "first_basis" | "latest_at" | "latest_basis">,
                           zone: string): string[] {
  const first = timeLine(story.first_at, story.first_basis, zone, "First reported");
  if (story.first_at === story.latest_at) return [first];
  return [first, timeLine(story.latest_at, story.latest_basis, zone, "Latest report")];
}

const kindsOf = (news: number, official: number) =>
  [news ? plural(news, "newsroom", "newsrooms") : "",
   official ? plural(official, "official statement", "official statements") : ""].filter(Boolean).join(", ");

/** "4 reports from 3 publishers: 1 confirmed reporting origin (1 official statement) and 1 possible origin (1 newsroom)
 * whose independence is not established; 1 copy counted with its origin. 1 company statement, not independent."
 * Publishers are counted apart from reporting origins: one publisher, or several carrying one text (a wire copy, a
 * republished release), is one origin. An origin is confirmed only when its independence is established; one whose
 * independence is not established is a possible origin, never called independent (story-coverage-0.3). */
export function coverageText(coverage: Coverage | (CoverageCounts & { reports: number })): string {
  const reports = `${plural(coverage.reports, "report", "reports")} from ` +
    plural(coverage.publishers, "publisher", "publishers");
  const copies = coverage.repeats > 0 ? `${plural(coverage.repeats, "copy", "copies")} counted with ` +
    `${coverage.repeats === 1 ? "its" : "their"} origin` : "";
  if (coverage.reporting_origins === 0) {  // Only companies' own statements: no reporting origin to count.
    return `${reports}: ${coverage.reports === 1 ? "a company statement" : "company statements"} (a company's own ` +
      `words), not independent reporting${copies ? `; ${copies}` : ""}.`;
  }
  const confirmed = coverage.confirmed_news + coverage.confirmed_official;
  const possible = coverage.possible_news + coverage.possible_official;
  const groups: string[] = [];
  if (confirmed > 0) {
    const name = confirmed === 1 && possible === 0 ? "1 reporting origin"
      : plural(confirmed, "confirmed reporting origin", "confirmed reporting origins");
    groups.push(`${name} (${kindsOf(coverage.confirmed_news, coverage.confirmed_official)})`);
  }
  if (possible > 0) {
    groups.push(`${plural(possible, "possible origin", "possible origins")} ` +
      `(${kindsOf(coverage.possible_news, coverage.possible_official)}) whose independence is not established`);
  }
  let text = `${reports}: ${groups.join(" and ")}`;
  if (copies) text += `; ${copies}`;
  text += ".";
  if (coverage.company_statements > 0) {
    text += ` ${plural(coverage.company_statements, "company statement", "company statements")}, the company's own ` +
      "words, not independent.";
  }
  return text;
}

export const BRIEF_STATE_TEXT: Record<BriefState, string> = {
  published: "Brief ready",
  none: "Awaiting a brief",
  withdrawn: "Brief withdrawn",
  not_permitted: "Headline only: its publisher does not permit a summary",
  insufficient: "Not enough material for a brief",
};

/** What a brief rests on, who prepared it and whether a person read it, and its time stamps. */
export function provenance(brief: Brief, zone: string): string[] {
  const review = brief.review.state === "written_by_editor" ? "" : ` ${brief.review.statement}`;
  const lines = [`${brief.method_label}${review} Version ${brief.version}, prepared ` +
    `${inZone(brief.prepared_at, zone)}, published ${inZone(brief.published_at, zone)}.`, brief.material.statement];
  if (brief.reports_since > 0) {
    lines.push(`${plural(brief.reports_since, "report has", "reports have")} arrived since this brief was prepared; ` +
      "it does not reflect them. They are listed under Sources.");
  }
  return lines;
}

export const USE_TEXT: Record<StorySource["use"], string> = {
  material: "Used for this brief.",
  permitted: "Its publisher allows summaries; not used by the current brief.",
  listed: "Listed and linked only, never used for summaries or analysis: its publisher's terms do not allow it, or " +
    "only its headline is held (an article found through a news index).",
};

/** The source's line about its publication time, as the feed states it. */
export function publishedText(source: StorySource, zone: string): string {
  const published = source.published;
  if (published.state === "stated" && published.utc) return `Published ${inZone(published.utc, zone)}`;
  if (published.state === "date_only" && published.date) return `Dated ${published.date} (no time stated)`;
  if (published.as_stated) {
    return `The feed's time (“${published.as_stated.replace(/\s+/g, " ")}”) is not a usable instant; first seen ` +
      inZone(source.first_seen_at, zone);
  }
  return `No publication time stated; first seen ${inZone(source.first_seen_at, zone)}`;
}

/** Whether the story is in Hot now, from its ranking signals as the server gave them (news-rank-0.3): a major mark
 * keeps it there; otherwise an older story, one covered only by company statements, or one whose economic relevance is
 * not established, is not. */
export function inHotNow(page: Pick<StoryPage, "signals" | "older">): boolean {
  const said = new Set(page.signals.map((row) => row.signal));
  if (said.has("priority")) return true;
  return !page.older && !said.has("statements_only") && !said.has("relevance");
}

/** A headline awaiting an assessment or an editor, in a few words: why it is not among the news yet. */
export const AWAITING_TEXT: Record<(typeof AWAITING_STATES)[number], string> = {
  pending: "Not assessed yet",
  restricted: "Not assessed: its publisher's terms allow no automated assessment",
  needs_review: "Assessment unclear: awaiting an editor",
  unavailable: "Assessment failed: awaiting an editor",
  insufficient: "Too little information to tell",
};

/** An economic dimension's label: the server's own word, capitalised. */
export const dimensionLabel = (dimension: Dimension) => dimension[0].toUpperCase() + dimension.slice(1);

/** Why the story is (or is not) in the economic news, and who decided: its state, the explanation and the basis. */
export function relevanceLines(relevance: Relevance): string[] {
  const lines = [relevance.statement];
  if (relevance.explanation) lines.push(relevance.explanation);
  if (relevance.basis_label) lines.push(relevance.basis_label);
  if (relevance.current === false) {
    lines.push("It was assessed before its latest reports or texts arrived; a new assessment is due.");
  }
  return lines;
}

/** The brief's label in a few words: who prepared it and whether a person read it ("AI-assisted · not read by an
 * editor"). Every word comes from the brief's own authorship and recorded review. */
export function authorshipTag(brief: Pick<Brief, "authorship" | "review">): string {
  const who = { editor: "Written by an editor", ai_model: "AI-drafted", ai_assistant: "AI-assisted",
                synthetic: "Synthetic example" }[brief.authorship];
  if (brief.review.state === "written_by_editor") return who;
  return `${who} · ${brief.review.state === "read_by_editor" ? "read by an editor" : "not read by an editor"}`;
}

const PREPARED_BY = { editor: "written by an editor", ai_model: "AI-drafted", ai_assistant: "AI-assisted",
                      synthetic: "a synthetic example" } as const;

/** That the brief replaced one readers were shown before, and when (null for a first version). */
export function briefUpdated(brief: Pick<Brief, "revisions" | "version">, zone: string): string | null {
  const history = brief.revisions;
  if (history.updated_at === null || history.earlier.length === 0) return null;
  return `Updated ${inZone(history.updated_at, zone)}: version ${brief.version} replaces version ` +
    `${history.earlier[0].version}, which stays readable below.`;
}

/** One earlier published version, as the brief's history lists it. */
export function earlierLine(row: Brief["revisions"]["earlier"][number], zone: string): string {
  const recorded = row.recorded_as ? `; first recorded as ${PREPARED_BY[AUTHORSHIP_OF[row.recorded_as]]}` : "";
  const corrects = row.corrects ? `, correcting who prepared version ${row.corrects}` : "";
  return `Version ${row.version} (${PREPARED_BY[row.authorship]}${recorded}${corrects}), published ` +
    `${inZone(row.published_at, zone)}, from ${plural(row.reports, "report", "reports")}` +
    `${row.explained ? ", with an economic explanation" : ""}.`;
}


/** The sources a brief rests on, numbered as the Sources section lists them: "The White House [1], [2]". */
export function briefSources(brief: Pick<Brief, "material">, number: (entry: string) => number): string {
  const byPublisher = new Map<string, number[]>();
  for (const row of brief.material.reports) {
    byPublisher.set(row.publisher, [...(byPublisher.get(row.publisher) ?? []), number(row.entry_id)]);
  }
  return [...byPublisher].map(([publisher, numbers]) =>
    `${publisher} ${numbers.sort((a, b) => a - b).map((value) => `[${value}]`).join(", ")}`).join("; ");
}

/** What the server holds of a source's publication text, in one line, or null when there is nothing to say (a
 * publisher whose pages are not read for their text). */
export function textLine(text: TextState, zone: string): string | null {
  const when = text.retrieved_at ? inZone(text.retrieved_at, zone) : "";
  switch (text.state) {
    case "full_text": return `Full text retained from the publisher's page (${text.characters?.toLocaleString("en-US")} ` +
      `characters, retrieved ${when}).`;
    case "partial_text": return `Part of the text retained from the publisher's page (${text.characters
      ?.toLocaleString("en-US")} characters, retrieved ${when}): ${text.partial_reason}.`;
    case "failed": return `The publication's text could not be read: ${text.detail}. Its headline and excerpt are used.`;
    case "not_retrieved": return "The publication's text has not been retrieved; its headline and excerpt are used.";
    default: return null;
  }
}

/** One material report's basis in a few words: its publication text, or its headline and excerpt. */
export function materialBasis(row: Pick<MaterialReport, "text" | "excerpt">): string {
  if (row.text?.state === "full_text") return `Full text, ${row.text.characters.toLocaleString("en-US")} characters`;
  if (row.text?.state === "partial_text") {
    return `Part of the text, ${row.text.characters.toLocaleString("en-US")} characters (${row.text.partial_reason})`;
  }
  return row.excerpt ? "Headline and the feed's excerpt" : "Headline only";
}

/** A brief's summary for a story card: whole sentences up to about 260 characters (a single first sentence up to
 * about 360), otherwise cut at a word with an ellipsis; the full brief is a click away. Nothing is rewritten. */
export function briefPreview(summary: string, limit = 260): string {
  const text = summary.trim();
  if (text.length <= limit) return text;
  // Sentence boundaries must cover the whole prefix. A punctuation-only matcher could start after the dots in
  // "U.S." or a decimal, silently dropping the beginning of a brief. The fallback below also preserves the prefix.
  const sentences = typeof Intl.Segmenter === "function"
    ? Array.from(new Intl.Segmenter("en", { granularity: "sentence" }).segment(text), (part) => part.segment) : [];
  let kept = "";
  for (const sentence of sentences) {
    if ((kept + sentence).trim().length > limit) break;
    kept += sentence;
  }
  if (kept.trim()) return kept.trim();
  const first = sentences[0]?.trim() ?? "";
  if (first && first.length <= Math.round(limit * 1.4)) return first;  // One long sentence: whole, not cut.
  const cut = text.slice(0, limit);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), 1)).trimEnd()}…`;
}

/** What going deeper needs on this server, stage by stage, from the account's own reasons (user-api-0.2): preparing
 * needs an Effort the credit terms offer; a quote needs those terms, a daily limit and credits; running needs the
 * server's paid sending and the person's approval. Nothing here sets the terms or grants anything. */
export function deeperStages(account: Pick<Account, "analysis" | "efforts">): { stage: string; ready: boolean;
  text: string }[] {
  const reasons = new Set((account.analysis.reasons ?? (account.analysis.reason ? [{ reason:
    account.analysis.reason }] : [])).map((row) => row.reason));
  const terms = !reasons.has("no_credit_policy") && !reasons.has("no_effort_enabled") && account.efforts.length > 0;
  const quote = terms && !reasons.has("no_daily_limit") && !reasons.has("no_credits_allocated");
  return [
    { stage: "prepare", ready: terms, text: terms ? "Your source and analysis can be prepared now; that is free."
      : reasons.has("no_credit_policy") ? "No credit terms are published on this server, so no Effort is offered and " +
        "nothing can be prepared, quoted or run yet. Nothing has been chosen for you: an administrator publishes " +
        "credit terms under Policy & settings." : "No Effort is offered on this server yet. Ask the administrator." },
    { stage: "quote", ready: quote, text: quote ? "Its credit quote can then be shown." : !terms
      ? "A credit quote needs published credit terms." : "A credit quote needs a daily limit and credits for your " +
        "account. Ask the administrator." },
    { stage: "run", ready: quote && !reasons.has("sending_disabled") && !reasons.has("no_credits_available"),
      text: reasons.has("sending_disabled") ? "Running an analysis is switched off on this server: even with a quote, " +
        "nothing would be sent." : reasons.has("no_credits_available") ? "You have no credits available to run it."
        : "It runs only after you approve its quote." },
  ];
}

/** A card's brief label from the brief's own record: "Brief · AI-assisted · not read by an editor", "Brief · Written
 * by an editor"; a story without a published brief says why. Nothing here assumes who prepared it. */
export function briefTag(brief: StoryCard["brief"]): string {
  if (brief.state !== "published" || brief.authorship === null || brief.review === null) {
    return BRIEF_STATE_TEXT[brief.state];
  }
  return `Brief · ${authorshipTag({ authorship: brief.authorship, review: { state: brief.review, statement: "" } })}`;
}

/** A story's reporting origins in a few words, counted as coverageText counts them (story-coverage-0.3): confirmed
 * origins apart from possible ones, whose independence is not established, and the publishers apart from both. */
export function originsLine(coverage: CoverageCounts): string {
  const confirmed = coverage.confirmed_news + coverage.confirmed_official;
  const possible = coverage.possible_news + coverage.possible_official;
  const parts: string[] = [];
  if (confirmed > 0) parts.push(`${confirmed} confirmed`);
  if (possible > 0) parts.push(`${possible} possible, independence not established`);
  if (coverage.company_origins > 0) {
    parts.push(`${plural(coverage.company_origins, "company statement", "company statements")}, not independent`);
  }
  const counted = coverage.reporting_origins === 0 ? "none: company statements only" : parts.join("; ");
  return `Reporting origins: ${counted} · ${plural(coverage.publishers, "publisher", "publishers")}`;
}

/** What a relevance decision rests on, in words that never call a missing or unfinished assessment a judgement. */
export function relevanceBasisLine(relevance: Pick<Relevance, "state" | "basis">): string {
  if (relevance.state === "pending" || relevance.state === "restricted") return "No assessment has been made.";
  if (relevance.state === "needs_review" || relevance.state === "unavailable") {
    return "No assessment has been completed; an editor has not decided yet.";
  }
  const who = relevance.basis === "editor" ? "An editor's judgement"
    : relevance.basis === "synthetic" ? "A SYNTHETIC judgement" : "A judgement made with AI";
  return `${who} from the story's sources, not a measured market impact.`;
}
