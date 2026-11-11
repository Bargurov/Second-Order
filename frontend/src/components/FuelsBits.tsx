import { formatDay } from "../format";
import type { MechanismFile, SourceItem } from "../fuels";
import { authorship } from "../fuelsNote";
import { SOURCE_COPY } from "../fuelsSituation";

const LETTER = { explanation: "E", sourced: "S" } as const;

/** What kind of statement is shown, beside Kind's kinds of number: E a possible explanation, S a sourced claim. Only
 * the legend shows S: the situation note's sourced claims are attributed in its own text (its Stage 1 labels stay), and
 * the sections below carry none. The accessible name is short, so a heading or summary holding the badge still reads
 * cleanly; the longer title is the hover text. */
export function StatementKind({ kind, label, title = label }: { kind: keyof typeof LETTER; label: string;
  title?: string }) {
  return <span className="ct-kind" data-kind={kind} title={title} aria-label={label}>{LETTER[kind]}</span>;
}

/** The E badge every driver row and sector card carries. */
export function Explanation() {
  return <StatementKind kind="explanation" label={SOURCE_COPY.explanationLabel} title={SOURCE_COPY.explanationTitle} />;
}

/** A mechanism's list of short texts, in their committed order. */
export function TextList({ items }: { items: string[] }) {
  return <ul>{items.map((text, index) => <li key={index}>{text}</li>)}</ul>;
}

/** One cited source: title (linked), publisher, date when it has one, the day it was checked and, optionally, where in
 * it the statement is supported. */
export function SourceLine({ source, locator = true }: { source: SourceItem; locator?: boolean }) {
  return (
    <>
      <a className="library-external" href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
      , {source.publisher}{source.date && <>, {formatDay(source.date)}</>}
      {" · "}<span className="fu-src-checked">{SOURCE_COPY.checked} {formatDay(source.checked_on)}</span>
      {locator && source.locator && <>{" · "}<span className="fu-src-locator">{source.locator}</span></>}
    </>
  );
}

/** An item's sources, or plainly that none is attached. */
export function SourceList({ sources }: { sources: SourceItem[] }) {
  if (sources.length === 0) return <p className="fu-no-source">{SOURCE_COPY.none}</p>;
  return (
    <ul className="fu-src-list">
      {sources.map((source, index) => <li key={`${index}-${source.url}`}><SourceLine source={source} /></li>)}
    </ul>
  );
}

/** Who stands behind a mechanism file: an AI draft is never presented as the owner's view. */
export function MechanismReview({ part, name }: { part: Extract<MechanismFile<unknown>, { state: "written" }>;
  name: string }) {
  return (
    <p className="fu-mech-review" data-review={part.review.state} data-part={name}>
      {authorship(part.author, part.review)} · {SOURCE_COPY.prepared} {formatDay(part.prepared_on)}
    </p>
  );
}
