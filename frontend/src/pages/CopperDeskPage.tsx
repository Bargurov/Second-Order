import { useEffect, useState, type ReactNode } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import { NoteBlock, NoteWriter } from "../components/ResearchNotes";
import {
  comparisonPath, datedLine, fetchCopperResearch, newestFirst, openQuestions, STATE_LABEL, subjectPath,
  type ComparisonView, type CopperResearchView,
} from "../copperResearch";
import { Link } from "../router";
import "../library.css";
import "../policyResearch.css";
import "../thesis.css";
import "../eventChains.css";
import "../copperResearch.css";

export const PAGE_SENTENCE = "One place for the copper research: its pages, what changed between two retained "
  + "publications, and your own notes. Nothing here is a research score.";
const NOT_VERIFIED = "Not shown while the saved notes cannot be verified.";
/** The questions are the owner's words too. One closes when a later note on its subject follows it. */
export const QUESTIONS_MARK = "Your own questions, from your notes: not a source's and not the assistant's. A question "
  + "closes when a later note on its subject follows it.";

function Part({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="cr-part" data-part={id} aria-labelledby={`cr-part-${id}`}>
      <h2 id={`cr-part-${id}`}>{title}</h2>
      {children}
    </section>
  );
}

function Comparison({ item }: { item: ComparisonView }) {
  return (
    <li data-comparison={item.id} data-comparison-state={item.state}>
      <p className="cr-item-title"><Link to={comparisonPath(item.id)}>{item.title}</Link>
        {item.historical && <>{" "}<span className="cr-tag" data-tag="historical">Historical</span></>}</p>
      <p className="cr-line" data-publication="earlier">Earlier: {item.earlier.name}, {datedLine(item.earlier)}.</p>
      <p className="cr-line" data-publication="later">Later: {item.later.name}, {datedLine(item.later)}.</p>
      <p className="cr-line" data-line="state">State: <strong>{STATE_LABEL[item.state]}</strong>.</p>
    </li>
  );
}

/**
 * The copper desk (/copper, admin only): the five copper pages with one line each, the comparisons of two retained
 * publications, the owner's open questions and notes, and the note form. The reply is shown only after the
 * fail-closed reader (copperResearch.ts) has accepted it; the page computes nothing. The last accepted view stays on
 * screen while a reload runs, so unsent text in the form is never lost to a reload.
 */
export function CopperDeskPage() {
  const [loaded, retry] = useLoad(fetchCopperResearch, "copper-research");
  const [shown, setShown] = useState<CopperResearchView | null>(null);
  useEffect(() => { document.title = "Copper desk · Second Order"; }, []);
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
  const notes = shown.notes;
  const questions = openQuestions(notes);
  return (
    <article className="library-case cr-page" data-page="copper-desk">
      <header className="library-case-header" aria-labelledby="cr-title">
        <p className="kicker">Copper research</p>
        <h1 id="cr-title">Copper desk</h1>
        <p className="thesis-disclaimer" data-sentence="page">{PAGE_SENTENCE}</p>
      </header>
      {loaded.state === "error" && (
        <p className="ec-error-banner" role="alert">The copper research could not be refreshed: {loaded.message}{" "}
          <button type="button" className="button" onClick={retry}>Try again</button></p>)}

      <Part id="pages" title="Pages">
        <ul className="cr-list">{shown.desk.pages.map((page) => (
          <li key={page.id} data-desk-page={page.id}>
            <p className="cr-item-title"><Link to={page.path}>{page.title}</Link></p>
            <p className="cr-line" data-line="what">{page.what}</p>
            {page.problem !== null ? <p className="ec-withheld" data-line="problem">{page.problem}</p>
              : page.status !== null && <p className="cr-line" data-line="status">{page.status}</p>}
          </li>))}</ul>
      </Part>

      <Part id="comparisons" title="What changed between two publications">
        {shown.comparisons.length === 0 ? <p className="ec-none">No comparison is published.</p>
          : <ul className="cr-list">{shown.comparisons.map((item) => <Comparison key={item.id} item={item} />)}</ul>}
      </Part>

      <Part id="questions" title="Open questions">
        {notes.state === "invalid" ? <p className="ec-none">{NOT_VERIFIED}</p>
          : questions.length === 0 ? <p className="ec-none">No open question.</p>
            : <>
              <p className="rn-mark" data-mark="questions">{QUESTIONS_MARK}</p>
              <ul className="cr-list">{questions.map((note) => (
                <li key={note.note_id} data-open-question={note.note_id}>
                  <p className="ec-own-text" dir="auto">{note.question}</p>
                  <p className="cr-line">{note.subject_title !== null
                    ? <Link to={subjectPath(note.about)}>{note.subject_title}</Link>
                    : `The ${note.about.kind} ${note.about.id}, which is no longer published`}</p>
                </li>))}</ul>
            </>}
      </Part>

      <Part id="notes" title="My notes">
        {notes.state === "invalid" ? <p className="ec-none">{NOT_VERIFIED}</p>
          : notes.items.length === 0 ? <p className="ec-none">No note is saved.</p>
            : newestFirst(notes.items).map((note) => <NoteBlock key={note.note_id} note={note} />)}
      </Part>

      <Part id="write" title="Write a note">
        <NoteWriter view={shown} about={null} onReload={retry} />
      </Part>
    </article>
  );
}
