import { useEffect, useRef, useState } from "react";
import {
  closedReason, fetchCopperResearch, latestNoteAbout, MAX_EXPECTATION, MAX_NOTE, MAX_QUESTION, noteBody, saveNote,
  settleNote, subjectKey, subjectLabel, subjectPath, type About, type CopperResearchView, type NoteBody,
  type NoteView, type Subject,
} from "../copperResearch";
import { formatUtc } from "../format";
import { guardLeaving } from "../leave";
import { Link } from "../router";

export const PERSONAL_MARK =
  "Personal note: the owner's view. Not a source, not an AI draft, not part of any research score.";
const DISCARD_QUESTION = "Discard your unsaved note?";
const CONFLICT = "Another note was saved from the same starting point. Nothing was sent again; reload to see it.";
const NOT_SAVED = "Not saved. Your text is kept; you may send it again.";
const UNVERIFIABLE = "The saved notes cannot be verified on this machine. Nothing was sent again.";
const NOTE_STATE: Record<NoteView["state"], string> = { current: "Current", earlier_basis: "Earlier basis" };
const DOCUMENT_STATE: Record<string, string> = {
  verified: "matches its acquisition record", changed: "differs from its acquisition record",
  missing: "is missing", superseded: "has been superseded", unreadable: "cannot be read",
};

// ---------------------------------------------------------------- a saved note

/** What a note was saved on, in words: the version of its subject (and, for a chain, of the thesis). */
function basisLine(note: NoteView): string {
  const basis = note.basis;
  if (basis.comparison !== undefined) return `Comparison version ${basis.comparison.version}.`;
  if (basis.chain !== undefined) {
    return `Chain version ${basis.chain.version}${basis.thesis ? `, thesis version ${basis.thesis.version}` : ""}.`;
  }
  return basis.thesis !== undefined ? `Thesis version ${basis.thesis.version}.` : "";
}

/**
 * One saved note of the owner's, in a block of its own: the fixed mark, when it was really saved and by whom, its
 * subject, and the owner's words as served (figures withheld while a document of its basis does not verify). An
 * expectation is never settled here: it reads as the server's line says.
 */
export function NoteBlock({ note }: { note: NoteView }) {
  const expectation = note.expectation;
  return (
    <article className="ec-owner rn-note" data-note={note.note_id} data-note-state={note.state}>
      <p className="rn-mark" data-mark="personal">{PERSONAL_MARK}</p>
      <p className="rn-signed">Saved {formatUtc(note.saved_at)} by {note.account.username}</p>
      <p className="rn-subject" data-note-subject={note.about.kind}>About:{" "}
        {note.subject_title !== null ? <Link to={subjectPath(note.about)}>{note.subject_title}</Link>
          : <span>the {note.about.kind} {note.about.id}, which is no longer published</span>}</p>
      {note.hindsight !== null && <p className="rn-hindsight" data-hindsight="">{note.hindsight}</p>}
      <p className="ec-own-text" data-note-text="" dir="auto">{note.text}</p>
      {expectation !== null && (
        <div className="rn-part" data-expectation={expectation.state}>
          <p className="rn-label">Expectation:</p>
          <p className="ec-own-text" data-expectation-text="" dir="auto">{expectation.text}</p>
          {expectation.check_by !== null && <p className="rn-line" data-check-by="">Check by {expectation.check_by}</p>}
          <p className="rn-line" data-expectation-status="">{expectation.status}</p>
        </div>)}
      {note.question !== null && (
        <div className="rn-part" data-question="">
          <p className="rn-label">Question for the next check:</p>
          <p className="ec-own-text" data-question-text="" dir="auto">{note.question}</p>
        </div>)}
      <p className="rn-line" data-state-line=""><strong>{NOTE_STATE[note.state]}</strong></p>
      {note.differs.length > 0 && (
        <ul className="ec-reasons" data-differs="">{note.differs.map((line) => <li key={line}>{line}</li>)}</ul>)}
      {note.masked && <p className="ec-withheld" data-masked="">Figures withheld: {note.mask_reason}</p>}
      {note.followed_by !== null && <p className="rn-line" data-followed="">A later note follows this one.</p>}
      {note.follows !== null && <p className="rn-line" data-follows="">Follows an earlier note.</p>}
      <details className="ec-basis">
        <summary>Basis</summary>
        <p>{basisLine(note)}</p>
        <ul>{note.basis_documents.map((doc) => (
          <li key={doc.ref} data-document-state={doc.state}>{doc.name} {DOCUMENT_STATE[doc.state] ?? doc.state}.</li>))}
        </ul>
      </details>
    </article>
  );
}

// ---------------------------------------------------------------- writing a note

/** Unsaved text is guarded on a link, Back or Forward and on the browser's own unload. */
function useUnsavedGuard(dirty: boolean) {
  const flag = useRef(false);
  flag.current = dirty;
  useEffect(() => guardLeaving(() => (flag.current ? DISCARD_QUESTION : null)), []);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
}

/** The note being written. It lives above the form, so a reload that closes or removes the form keeps it. */
function useNoteDraft() {
  const [subject, setSubject] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [expectation, setExpectation] = useState("");
  const [checkBy, setCheckBy] = useState("");
  const [question, setQuestion] = useState("");
  const [follows, setFollows] = useState(false);
  const clear = () => { setText(""); setExpectation(""); setCheckBy(""); setQuestion(""); setFollows(false); };
  const dirty = text.trim() !== "" || expectation.trim() !== "" || question.trim() !== "";
  return { subject, setSubject, text, setText, expectation, setExpectation, checkBy, setCheckBy, question, setQuestion,
    follows, setFollows, clear, dirty };
}
type Draft = ReturnType<typeof useNoteDraft>;

/** idle: may send. sending. unconfirmed: the reply was lost, only the check is offered. locked: nothing is sent. */
type Phase = "idle" | "sending" | "unconfirmed" | "locked";

/**
 * One note save with its settling rules, as the event chains' saves have them: the text stays in the form until it is
 * known to be saved, and a lost reply is settled from the saved notes, never by sending again. `refused` is true while
 * the message is a refusal or an unsettled outcome rather than a saved one.
 */
function useNoteSave(onReload: () => void, onSaved: () => void) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [refused, setRefused] = useState(false);
  const [sent, setSent] = useState<NoteBody | null>(null);

  const show = (text: string | null, kept: boolean) => { setMessage(text); setRefused(kept); };
  const finish = (text: string) => { show(text, false); setSent(null); setPhase("idle"); onSaved(); onReload(); };

  async function send(body: NoteBody) {
    setPhase("sending");
    show(null, false);
    const reply = await saveNote(body);
    if (reply.state === "ready") return finish("Saved.");
    if (reply.state === "blocked") {
      show(reply.message, true);
      setPhase("idle");
      onReload();
      return;
    }
    if (reply.state === "unconfirmed") {
      setSent(body);
      show(reply.message, true);
      setPhase("unconfirmed");
      return;
    }
    show(reply.message, true);
    setPhase("idle");
  }

  async function check() {
    if (sent === null) return;
    setPhase("sending");
    const loaded = await fetchCopperResearch();
    if (loaded.state !== "ready") {
      show(`The saved notes could not be read: ${loaded.state === "loading" ? "still loading." : loaded.message} `
        + "Nothing was sent again.", true);
      setPhase("unconfirmed");
      return;
    }
    const outcome = settleNote(loaded.data, sent);
    if (outcome === "saved") return finish("Saved.");
    if (outcome === "conflict") { show(CONFLICT, true); setPhase("locked"); return; }
    if (outcome === "unverifiable") { show(UNVERIFIABLE, true); setPhase("locked"); return; }
    show(NOT_SAVED, true);
    setSent(null);
    setPhase("idle");
  }
  /** The owner edits the note: a message about the earlier text is cleared (an unsettled or locked one stays). */
  const edited = () => { if (phase === "idle") show(null, false); };
  return { phase, message, refused, send, check, edited };
}
type Save = ReturnType<typeof useNoteSave>;

function Outcome({ save }: { save: Save }) {
  return (
    <>
      {save.message !== null && save.phase !== "unconfirmed" && (
        <p className="ec-message" role="status">{save.message}</p>)}
      {save.phase === "unconfirmed" && (
        <div className="ec-message is-unconfirmed" role="alert">
          <p><strong>Not confirmed.</strong> {save.message} This note may or may not have been saved. Your text is
            kept, and nothing is sent again automatically. Check the saved notes before saving again.</p>
          <button type="button" className="button" onClick={save.check}>Check the saved notes</button>
        </div>)}
    </>
  );
}

/**
 * The note form. `subject` is what the note is about now; `choices` is set where the owner picks the subject (the
 * desk) and null where the page fixes it (a comparison's page). `closed`: nothing can be sent (the saved notes cannot
 * be verified, or no subject is served); the form then stays only to keep its text and its last message.
 */
function NoteForm({ view, subject, choices, draft, save, closed }: { view: CopperResearchView; subject: Subject | null;
  choices: Subject[] | null; draft: Draft; save: Save; closed: boolean }) {
  const open = save.phase === "idle";
  const earlier = subject === null ? null : latestNoteAbout(view.notes, subject);
  const reason = subject === null || closed ? null : closedReason(subject);
  const expects = draft.expectation.trim() !== "";
  const ready = open && !closed && subject !== null && subject.state === "available" && draft.text.trim() !== "";
  const change = (set: (value: string) => void) => (event: { target: { value: string } }) => {
    save.edited();
    set(event.target.value);
  };
  // A saved note can never be edited or deleted, so Enter in a one-line control must not send the form: only the
  // save button does (by a click, or by Enter or Space while it holds the focus).
  const noImplicitSave = (event: { key: string; preventDefault: () => void }) => {
    if (event.key === "Enter") event.preventDefault();
  };
  return (
    <form className="ec-form rn-form" data-form="note" onSubmit={(event) => {
      event.preventDefault();
      if (!ready || subject === null) return;
      save.send(noteBody(view.notes, subject, { text: draft.text, expectation: draft.expectation,
        checkBy: draft.checkBy, question: draft.question,
        follows: draft.follows && earlier !== null ? earlier.note_id : null }));
    }}>
      {choices !== null && subject !== null && (
        <label className="ec-field">This note is about
          <select value={subjectKey(subject)} disabled={!open} data-field="subject" onKeyDown={noImplicitSave}
                  onChange={(event) => {
            save.edited();
            draft.setSubject(event.target.value);
            draft.setFollows(false);
          }}>{choices.map((item) => (
            <option key={subjectKey(item)} value={subjectKey(item)}>{subjectLabel(item)}</option>))}</select></label>)}
      <label className="ec-field">Your note, in your own words (not a quotation of a source)
        <textarea dir="auto" value={draft.text} maxLength={MAX_NOTE} rows={4} readOnly={!open} data-field="text"
                  onChange={change(draft.setText)} /></label>
      <p className="ec-count">{draft.text.length} of {MAX_NOTE} characters</p>
      <label className="ec-field">An expectation, in your own words (optional)
        <textarea dir="auto" value={draft.expectation} maxLength={MAX_EXPECTATION} rows={2} readOnly={!open}
                  data-field="expectation" onChange={change(draft.setExpectation)} /></label>
      <p className="ec-count">{draft.expectation.length} of {MAX_EXPECTATION} characters</p>
      <label className="ec-field">Check by (optional)
        <input type="date" value={draft.checkBy} disabled={!open || !expects} data-field="check-by"
               onKeyDown={noImplicitSave} onChange={change(draft.setCheckBy)} /></label>
      <label className="ec-field">A question for the next check (optional)
        <textarea dir="auto" value={draft.question} maxLength={MAX_QUESTION} rows={2} readOnly={!open}
                  data-field="question" onChange={change(draft.setQuestion)} /></label>
      <p className="ec-count">{draft.question.length} of {MAX_QUESTION} characters</p>
      {earlier !== null && (
        <label className="rn-check"><input type="checkbox" checked={draft.follows} disabled={!open} data-field="follows"
          onKeyDown={noImplicitSave}
          onChange={(event) => { save.edited(); draft.setFollows(event.target.checked); }} />{" "}
          This note follows my latest note on this subject</label>)}
      <button type="submit" className="button" disabled={!ready}>
        {save.phase === "sending" ? "Saving…" : "Save note"}</button>
      {reason !== null && <p className="ec-none" data-forms="closed">{reason}</p>}
      <Outcome save={save} />
    </form>
  );
}

/**
 * Writing a note on the copper research. `about` fixes the subject (a comparison's own page); null lets the owner pick
 * one of the served subjects (the desk). The draft and the save's outcome live here, above the form, so the reload a
 * save or a refusal causes never loses typed text; while the saved notes cannot be verified no form is offered, except
 * one that already holds text or a refusal, which stays, unable to send, beside the reason.
 */
export function NoteWriter({ view, about, onReload }: { view: CopperResearchView; about: About | null;
  onReload: () => void }) {
  const draft = useNoteDraft();
  const save = useNoteSave(onReload, draft.clear);
  useUnsavedGuard(draft.dirty);
  const wanted = about !== null ? subjectKey(about) : draft.subject;
  // The desk falls back to the first served subject; a page that fixes the subject never writes about another.
  const subject = view.subjects.find((item) => subjectKey(item) === wanted)
    ?? (about === null ? view.subjects[0] : null) ?? null;
  const invalid = view.notes.state === "invalid";
  const keep = draft.dirty || save.refused || save.phase !== "idle";
  const form = (closed: boolean) => (
    <NoteForm view={view} subject={subject} choices={about === null ? view.subjects : null} draft={draft} save={save}
              closed={closed} />);
  if (invalid) {
    return (
      <>
        <p className="ec-invalid" role="alert" data-notes="invalid">{view.notes.problem}</p>
        {keep && form(true)}
      </>
    );
  }
  if (subject === null) {
    return (
      <>
        <p className="ec-none" data-forms="closed">Nothing is served that a note can be written about.</p>
        {keep && form(true)}
      </>
    );
  }
  return form(false);
}
