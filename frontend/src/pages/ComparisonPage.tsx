import { useEffect, useState } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import { NoteBlock, NoteWriter } from "../components/ResearchNotes";
import {
  datedLine, DESK_PATH, fetchCopperResearch, newestFirst, notesAbout, priceLine, STATE_LABEL, type ComparisonRow,
  type ComparisonView, type CopperResearchView, type PriceFigure, type Publication, type RowSide,
} from "../copperResearch";
import { Link } from "../router";
import "../library.css";
import "../policyResearch.css";
import "../thesis.css";
import "../eventChains.css";
import "../copperResearch.css";

export const PREPARED_MARK = "Prepared by the assistant from retained sources; not reviewed by the owner.";
const SIDES = [["earlier", "Earlier"], ["later", "Later"]] as const;
const DOCUMENT_STATE: Record<string, string> = {
  verified: "matches its acquisition record", changed: "differs from its acquisition record",
  missing: "is missing", superseded: "has been superseded", unreadable: "cannot be read",
};
/** A publication whose record in the research (its title, form or date) is no longer the pinned one. */
const PUBLICATION_RECORD: Record<string, string> = {
  changed: "The research's record of this publication (its title, form or date) changed since it was pinned.",
  gone: "The research no longer lists this publication.",
  unreadable: "The research records cannot be read, so this publication's record is not checked.",
};
const SIDE_STATE: Record<string, string> = {
  verified: "The record is as it was pinned",
  record_changed: "The record's wording or place changed since it was pinned",
  record_gone: "The record is no longer in the research", record_unreadable: "The research records cannot be read",
};

function PublicationCard({ side, label, publication }: { side: string; label: string; publication: Publication }) {
  return (
    <div data-publication={side} data-document-state={publication.state}>
      <h3>{label}</h3>
      <p className="cr-item-title">{publication.name}</p>
      <p className="cr-line">{publication.title}</p>
      <p className="cr-line" data-line="dated">{datedLine(publication)}</p>
      <p className="ec-source-line">The retained document {DOCUMENT_STATE[publication.state] ?? publication.state}.</p>
      {publication.record !== "same" && (
        <p className="ec-withheld" data-line="record">{PUBLICATION_RECORD[publication.record]
          ?? "The research's record of this publication differs from the pinned one."}</p>)}
    </div>
  );
}

/** One line of a row: the source's own words with their place, or why they are withheld. Never a figure of its own. */
function Side({ side, label, line, publication }: { side: string; label: string; line: RowSide;
  publication: Publication }) {
  const record = SIDE_STATE[line.state];
  return (
    <div data-side={side} data-side-state={line.state}>
      <h4>{label}: {publication.name}, {datedLine(publication)}</h4>
      {line.quote !== null
        ? <blockquote className="ec-quote"><p>{line.quote}</p><footer>{line.where}</footer></blockquote>
        : <p className="ec-withheld">{line.problem}</p>}
      <p className="ec-source-line">{line.document.name} {DOCUMENT_STATE[line.document.state] ?? line.document.state}.
        {record !== undefined && <>{" "}{record}.</>}</p>
    </div>
  );
}

/** One row: its two lines side by side as written, the fixed sentence on whether they are one measure, and the
 * assistant's note on what each line measures. No difference, ratio or change between the two lines is shown. */
function Row({ row, comparison }: { row: ComparisonRow; comparison: ComparisonView }) {
  return (
    <section className="cr-row" data-row={row.id} aria-label={row.label}>
      <h3>{row.label}</h3>
      <div className="ec-sides" data-sides="">
        {SIDES.map(([side, label]) => (
          <Side key={side} side={side} label={label} line={row[side]} publication={comparison[side]} />))}
      </div>
      <p className="cr-sentence" data-sentence="measure">{row.sentence}</p>
      {row.note_withheld
        ? <p className="ec-withheld" data-row-note="withheld">The assistant's note is withheld with its source.</p>
        : row.note !== null && <p className="cr-row-note" data-row-note="shown">The assistant's note: {row.note}</p>}
    </section>
  );
}

function Price({ figure }: { figure: PriceFigure }) {
  const line = priceLine(figure);
  return (
    <li data-figure={figure.id} data-figure-state={figure.state}>
      {line !== null ? <span data-line="figure">{line}</span>
        : <>{figure.label !== null && <span>{figure.label}</span>}
          <span className="ec-withheld" data-line="problem">{figure.problem}</span></>}
      {figure.source !== null && <span className="ec-source-line">{figure.source.name}</span>}
    </li>
  );
}

/**
 * One comparison of two retained publications (/copper/comparisons/:id, admin only): both publications, each row's
 * two lines side by side in the sources' words, the retained price figures with their periods, and the owner's notes
 * on it. The reply is shown only after the fail-closed reader (copperResearch.ts) has accepted it. The page computes
 * nothing, and never a change between two lines. The last accepted view stays on screen while a reload runs.
 */
export function ComparisonPage({ id }: { id: string }) {
  const [loaded, retry] = useLoad(fetchCopperResearch, "copper-research");
  const [shown, setShown] = useState<CopperResearchView | null>(null);
  const comparison = shown?.comparisons.find((item) => item.id === id);
  useEffect(() => {
    document.title = `${comparison?.title ?? "Comparison"} · Copper desk · Second Order`;
  }, [comparison?.title]);
  useEffect(() => { if (loaded.state === "ready") setShown(loaded.data); }, [loaded]);
  if (shown === null) {
    if (loaded.state === "loading" || loaded.state === "ready") return <Skeleton />;
    return (
      <section className="state-panel" role="alert">
        <p>The copper research could not be read: {loaded.message}</p>
        <button type="button" className="button" onClick={retry}>Try again</button>
      </section>
    );
  }
  if (comparison === undefined) {
    return (
      <section className="state-panel" data-page="copper-comparison" data-missing="">
        <p className="kicker">Copper research · what changed</p>
        <p>No comparison has this id.</p>
        <p><Link to={DESK_PATH}>Copper desk</Link></p>
      </section>
    );
  }
  const about = { kind: "comparison" as const, id };
  const notes = notesAbout(shown.notes, about);
  return (
    <article className="library-case cr-page" data-page="copper-comparison" data-comparison={comparison.id}
             data-comparison-state={comparison.state}>
      <nav className="library-crumbs cr-crumbs" aria-label="Copper research">
        <Link to={DESK_PATH}>Copper desk</Link>
        <span>{comparison.title}</span>
      </nav>
      <header className="library-case-header" aria-labelledby="cr-title">
        <p className="kicker">Copper research · what changed</p>
        <h1 id="cr-title">{comparison.title}</h1>
        {comparison.historical_note !== null && (
          <p className="thesis-disclaimer" data-sentence="historical">{comparison.historical_note}</p>)}
        <p className="ec-mark" data-mark="prepared">{PREPARED_MARK}</p>
        <p className="ec-meta" data-line="state">State: <strong>{STATE_LABEL[comparison.state]}</strong>.</p>
        {comparison.reasons.length > 0 && (
          <ul className="ec-reasons">{comparison.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>)}
      </header>
      {loaded.state === "error" && (
        <p className="ec-error-banner" role="alert">The comparison could not be refreshed: {loaded.message}{" "}
          <button type="button" className="button" onClick={retry}>Try again</button></p>)}

      <section className="cr-part" data-part="publications" aria-labelledby="cr-part-publications">
        <h2 id="cr-part-publications">The two publications</h2>
        <div className="ec-sides">
          {SIDES.map(([side, label]) => (
            <PublicationCard key={side} side={side} label={label} publication={comparison[side]} />))}
        </div>
      </section>

      <section className="cr-part" data-part="rows" aria-labelledby="cr-part-rows">
        <h2 id="cr-part-rows">Line by line, as written</h2>
        {comparison.rows.map((row) => <Row key={row.id} row={row} comparison={comparison} />)}
      </section>

      <section className="cr-part" data-part="prices" aria-labelledby="cr-part-prices">
        <h2 id="cr-part-prices">Retained prices</h2>
        <ul className="cr-list cr-prices">
          {comparison.prices.figures.map((figure) => <Price key={figure.id} figure={figure} />)}</ul>
        <p className="cr-sentence" data-prices="text">{comparison.prices.text}</p>
      </section>

      <section className="cr-part" data-part="notes" aria-labelledby="cr-part-notes">
        <h2 id="cr-part-notes">My notes on this comparison</h2>
        {shown.notes.state === "invalid"
          ? <p className="ec-none">Not shown while the saved notes cannot be verified.</p>
          : notes.length === 0 ? <p className="ec-none">No note is saved on this comparison.</p>
            : newestFirst(notes).map((note) => <NoteBlock key={note.note_id} note={note} />)}
        <NoteWriter view={shown} about={about} onReload={retry} />
      </section>
    </article>
  );
}
