import { useEffect, useRef, useState } from "react";
import { guardLeaving } from "../leave";
import {
  fetchEventChains, readingBody, reviewBody, saveReading, saveReview, settle,
  type Action, type ChainView, type Judgment, type RecordReply, type SentSave,
} from "../eventChains";

export const SHORT_TERM = "Short term (up to 12 months after the event)";
export const LONG_TERM = "Long term (more than 12 months after it)";
export const JUDGMENT_LABEL: Record<Judgment, string> = {
  supports: "Supports the thesis", refutes: "Refutes the thesis", neither: "Neither", not_sure: "Not sure",
};
const JUDGMENTS: Judgment[] = ["supports", "refutes", "neither", "not_sure"];
const DISCARD_QUESTION = "Discard your unsaved text on the event chains page?";
const LINE_MAX = 280;
const NOTES_MAX = 1000;

const CONFLICT = "Another tab saved a different version from the same starting point. Nothing was sent again; reload to see it.";
const SUPERSEDED = "Saved; a newer version followed it.";
const NOT_SAVED = "Not saved. Your text is kept; you may send it again.";
const UNVERIFIABLE = "The saved versions cannot be verified on this machine. Nothing was sent again.";

/** Unsaved text is guarded on a link, Back or Forward and on the browser's own unload. */
export function useUnsavedGuard(dirty: boolean) {
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

/** idle: may send. sending. unconfirmed: the reply was lost, only the check is offered. locked: nothing more is sent. */
type Phase = "idle" | "sending" | "unconfirmed" | "locked";

/**
 * One owner save with its settling rules. The text stays in the form until it is known to be saved; a lost reply is
 * settled from the saved history, never by sending again. It lives above the form (in the card's Forms), so a refusal
 * stays on screen through the reload it causes, until the next save or until the owner edits the text (`edited`).
 * `refused` is true while the message is a refusal or an unsettled outcome rather than a saved one.
 */
export function useSave(chain: ChainView, onReload: () => void, onSaved: () => void) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [refused, setRefused] = useState(false);
  const [sent, setSent] = useState<SentSave | null>(null);

  const show = (text: string | null, kept: boolean) => { setMessage(text); setRefused(kept); };
  const finish = (text: string) => { show(text, false); setSent(null); setPhase("idle"); onSaved(); onReload(); };

  async function send(body: SentSave, run: () => Promise<Action<RecordReply>>) {
    setPhase("sending");
    show(null, false);
    const reply = await run();
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
    const loaded = await fetchEventChains();
    if (loaded.state !== "ready") {
      show(`The saved versions could not be read: ${loaded.state === "loading" ? "still loading." : loaded.message} Nothing was sent again.`, true);
      setPhase("unconfirmed");
      return;
    }
    const found = loaded.data.chains.find((item) => item.id === chain.id);
    const outcome = found === undefined ? "unverifiable" : settle(found.history, sent);
    if (outcome === "saved") return finish("Saved.");
    if (outcome === "superseded") return finish(SUPERSEDED);
    if (outcome === "conflict") { show(CONFLICT, true); setPhase("locked"); return; }
    if (outcome === "unverifiable") { show(UNVERIFIABLE, true); setPhase("locked"); return; }
    show(NOT_SAVED, true);
    setSent(null);
    setPhase("idle");
  }
  /** The owner edits the text: a message about the earlier text is cleared (an unsettled or locked one stays). */
  const edited = () => { if (phase === "idle") show(null, false); };
  return { phase, message, refused, send, check, edited };
}

export type Save = ReturnType<typeof useSave>;

function Outcome({ phase, message, onCheck }: { phase: Phase; message: string | null; onCheck: () => void }) {
  return (
    <>
      {message !== null && phase !== "unconfirmed" && <p className="ec-message" role="status">{message}</p>}
      {phase === "unconfirmed" && (
        <div className="ec-message is-unconfirmed" role="alert">
          <p><strong>Not confirmed.</strong> {message} This version may or may not have been saved. Your text is kept,
            and nothing is sent again automatically. Check the saved versions before saving again.</p>
          <button type="button" className="button" onClick={onCheck}>Check the saved versions</button>
        </div>)}
    </>
  );
}

function Judgments({ name, legend, value, onChange, disabled }:
  { name: string; legend: string; value: Judgment | null; onChange: (value: Judgment) => void; disabled: boolean }) {
  return (
    <fieldset className="ec-choices" disabled={disabled}>
      <legend>{legend}</legend>
      {JUDGMENTS.map((item) => (
        <label key={item}><input type="radio" name={name} value={item} checked={value === item}
                                 onChange={() => onChange(item)} /> {JUDGMENT_LABEL[item]}</label>))}
    </fieldset>
  );
}

export type ReadingDraft = { shortTerm: Judgment | null; setShortTerm: (value: Judgment | null) => void;
  longTerm: Judgment | null; setLongTerm: (value: Judgment | null) => void; line: string; setLine: (value: string) => void };

/** The reading being written. It lives above the form so that the form unmounting never discards it. */
export function useReadingDraft(): ReadingDraft {
  const [shortTerm, setShortTerm] = useState<Judgment | null>(null);
  const [longTerm, setLongTerm] = useState<Judgment | null>(null);
  const [line, setLine] = useState("");
  return { shortTerm, setShortTerm, longTerm, setLongTerm, line, setLine };
}

export type ReviewStatus = "approved" | "needs_revision";
export type ReviewDraft = { status: ReviewStatus | null; setStatus: (value: ReviewStatus | null) => void; notes: string;
  setNotes: (value: string) => void };

/** The review being written. Like the reading, it lives above the form, so a reload that closes the forms keeps it. */
export function useReviewDraft(): ReviewDraft {
  const [status, setStatus] = useState<ReviewStatus | null>(null);
  const [notes, setNotes] = useState("");
  return { status, setStatus, notes, setNotes };
}

/**
 * Your review of this version of the chain: approved, or needing revision, with notes in your own words. `closed`:
 * the chain no longer accepts saves; the form stays only to keep its text and its last message, and cannot send.
 */
export function ReviewForm({ chain, draft, save, blocked, closed }:
  { chain: ChainView; draft: ReviewDraft; save: Save; blocked: string | null; closed: boolean }) {
  const { status, setStatus, notes, setNotes } = draft;
  const open = save.phase === "idle";
  const ready = open && !closed && status !== null && blocked === null;
  return (
    <form className="ec-form" data-form="review" onSubmit={(event) => {
      event.preventDefault();
      if (status === null || !ready) return;
      save.send({ kind: "reviews", body: reviewBody(chain, status, notes) }, () => saveReview(chain, status, notes));
    }}>
      <h4>Your review of this version</h4>
      <fieldset className="ec-choices" disabled={!open}>
        <legend>Your review</legend>
        <label><input type="radio" name={`review-${chain.id}`} checked={status === "approved"}
                      onChange={() => { save.edited(); setStatus("approved"); }} /> Approved</label>
        <label><input type="radio" name={`review-${chain.id}`} checked={status === "needs_revision"}
                      onChange={() => { save.edited(); setStatus("needs_revision"); }} /> Needs revision</label>
      </fieldset>
      <label className="ec-field">Notes, in your own words (not a quotation of a source; refer to a step by its number)
        <textarea dir="auto" value={notes} maxLength={NOTES_MAX} rows={3} readOnly={!open}
                  onChange={(event) => { save.edited(); setNotes(event.target.value); }} /></label>
      <p className="ec-count">{notes.length} of {NOTES_MAX} characters</p>
      <button type="submit" className="button" disabled={!ready}>
        {save.phase === "sending" ? "Saving…" : "Save review"}</button>
      {blocked !== null && <span className="ec-blocked" data-blocked="review"> {blocked}</span>}
      <Outcome phase={save.phase} message={save.message} onCheck={save.check} />
    </form>
  );
}

/** Your reading of the chain, once this version is approved: one judgment for each horizon and one line. `closed` as
 * for the review form. */
export function ReadingForm({ chain, draft, save, closed }:
  { chain: ChainView; draft: ReadingDraft; save: Save; closed: boolean }) {
  const { shortTerm, setShortTerm, longTerm, setLongTerm, line, setLine } = draft;
  const open = save.phase === "idle";
  const ready = open && !closed && shortTerm !== null && longTerm !== null && line.trim() !== "";
  return (
    <form className="ec-form" data-form="reading" onSubmit={(event) => {
      event.preventDefault();
      if (!ready || shortTerm === null || longTerm === null) return;
      const body = readingBody(chain, shortTerm, longTerm, line);
      if (body === null) return;
      save.send({ kind: "readings", body }, () => saveReading(chain, shortTerm, longTerm, line));
    }}>
      <h4>Write your reading</h4>
      <Judgments name={`short-${chain.id}`} legend={SHORT_TERM} value={shortTerm}
                 onChange={(value) => { save.edited(); setShortTerm(value); }} disabled={!open} />
      <Judgments name={`long-${chain.id}`} legend={LONG_TERM} value={longTerm}
                 onChange={(value) => { save.edited(); setLongTerm(value); }} disabled={!open} />
      <label className="ec-field">One line, in your own words (not a quotation of a source; refer to a step by its number)
        <textarea dir="auto" value={line} maxLength={LINE_MAX} rows={2} readOnly={!open}
                  onChange={(event) => { save.edited(); setLine(event.target.value); }} /></label>
      <p className="ec-count">{line.length} of {LINE_MAX} characters</p>
      <button type="submit" className="button" disabled={!ready}>
        {save.phase === "sending" ? "Saving…" : "Save reading"}</button>
      <Outcome phase={save.phase} message={save.message} onCheck={save.check} />
    </form>
  );
}
