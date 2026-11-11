import { useEffect, useRef, useState, type FormEvent } from "react";
import { MAX_SOURCE_CHARACTERS } from "../../contracts/user.ts";
import { navigate } from "../../router";
import { useClient, useUnsaved, zoneOf } from "../context";
import { outcomeOf } from "../controller.ts";
import { href } from "../paths.ts";
import { HEADLINE_NOTE, SOURCE_SIZE_NOTE, SOURCE_URL_NOTE, sourceFormProblems } from "../present.ts";
import { clearPaste, peekPaste, type PasteOffer } from "../newsView.ts";
import { SOURCE_KEY, type SourceFields } from "../recovery.ts";
import type { Notice } from "../refusals.ts";
import { NoticeView } from "./NoticeView";

const pad = (value: number) => String(value).padStart(2, "0");
const offsetText = (minutes: number) => `${minutes < 0 ? "-" : "+"}${pad(Math.floor(Math.abs(minutes) / 60))}:${pad(Math.abs(minutes) % 60)}`;
/** Every half-hour offset in use, plus the three quarter-hour ones. The person chooses; nothing is assumed. */
const OFFSETS = [...Array.from({ length: 53 }, (_, index) => -720 + index * 30), 345, 525, 765]
  .sort((a, b) => a - b).map(offsetText);

type Fields = SourceFields;
const EMPTY: Fields = { headline: "", source_url: "", date: "", time: "", offset: "", text: "" };

/** Add a source: its headline, address, publication time with an explicit UTC offset, and its text. Saving it uses no
 * credits and runs nothing. A form typed when the session ended comes back here, as typed, for the same user only
 * (recovery.ts); it is saved only when the person saves it. */
export function NewSourcePage() {
  const { api, account, endSession, recovered, releaseRecovered } = useClient();
  const [fields, setFields] = useState<Fields>(EMPTY);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);
  const acting = useRef(false);
  const typed = Object.values(fields).some((value) => value.trim() !== "");
  const waiting = recovered[SOURCE_KEY]?.kind === "source" ? recovered[SOURCE_KEY] : null;
  const putBack = () => {
    if (!waiting) return;
    setFields(waiting.fields);
    setRestored(true);
    releaseRecovered(SOURCE_KEY);
  };
  useEffect(() => { if (waiting && !typed) putBack(); }, [waiting]);  // Into an empty form only; otherwise asked below.
  // A news entry's paste step (newsView.ts pasteOffer): into an empty form with nothing recovered waiting; otherwise
  // offered below, to replace the form only when the person asks.
  const [offer, setOffer] = useState<PasteOffer | null>(() => peekPaste());
  const [fromNews, setFromNews] = useState<PasteOffer | null>(null);
  const takeOffer = (taken: PasteOffer) => {
    setFields(taken.fields);
    setFromNews(taken);
    setOffer(null);
    setRestored(false);
  };
  useEffect(() => {
    clearPaste();
    if (offer && !waiting) takeOffer(offer);
  }, []);
  useUnsaved(SOURCE_KEY, typed && !saved ? { kind: "source", fields } : null);
  useEffect(() => { document.title = "Add a source · Second Order"; }, []);
  useEffect(() => { if (saved) navigate(href.source(saved)); }, [saved]);  // After the unsaved guard is released.

  const characters = Array.from(fields.text).length;
  const problems = sourceFormProblems(fields);
  const set = (key: keyof Fields) => (event: { target: { value: string } }) =>
    setFields((current) => ({ ...current, [key]: event.target.value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (acting.current) return;
    acting.current = true;
    setBusy(true);
    setNotice(null);
    const outcome = outcomeOf(await api.addSource({
      headline: fields.headline.trim(), source_url: fields.source_url.trim(),
      published_at: `${fields.date}T${fields.time}:00${fields.offset}`, source_text: fields.text,
    }), null, zoneOf(account));
    acting.current = false;
    setBusy(false);
    if (outcome.kind === "ok") {
      setFields(EMPTY);
      setSaved(outcome.data.source.source_id);
    } else if (outcome.kind === "session") endSession(outcome.reason);
    else setNotice(outcome.notice);
  };

  return (
    <>
      <header className="client-header">
        <p className="kicker">New source</p>
        <h1 className="client-title">Add a source</h1>
        <p className="client-lede">A publication you want analysed: its headline, address, when it was published, and its
          text as you have it. Saving it uses no credits and runs nothing (it counts as one of today's new sources); you
          choose an Effort next.</p>
      </header>
      <form className="card client-card client-form" onSubmit={(event) => void submit(event)}>
        {fromNews && !saved && (
          <div className="client-note client-from-news" data-from-news={fromNews.entryId}>
            <p>From the news: {fromNews.publisher}, “{fromNews.title}”.{" "}
              <a href={fromNews.link} target="_blank" rel="noreferrer">Open the official page</a></p>
            <ul>{fromNews.notes.map((note) => <li key={note}>{note}</li>)}</ul>
          </div>
        )}
        {offer && (
          <div className="client-notice is-unconfirmed" data-from-news="waiting">
            <p>The news entry “{offer.title}” is waiting to fill this form with its headline, address and the time its
              feed states.</p>
            <p className="client-actions">
              <button type="button" className="button button-quiet" onClick={() => takeOffer(offer)}>Fill the form from
                it (replaces this form)</button>
              <button type="button" className="client-link-button" onClick={() => setOffer(null)}>Leave it</button>
            </p>
          </div>
        )}
        {restored && typed && !saved && (
          <p className="client-note" role="status" data-recovered="source">The source you were adding when your session
            ended is back, as you left it. It is not saved: check it and save it yourself.</p>
        )}
        {waiting && typed && (
          <div className="client-notice is-unconfirmed" data-recovered="waiting">
            <p>The source you were adding when your session ended is waiting: “{waiting.fields.headline.trim() ||
              "untitled"}”.</p>
            <p className="client-actions">
              <button type="button" className="button button-quiet" onClick={putBack}>Put it back (replaces this form)</button>
              <button type="button" className="client-link-button" onClick={() => releaseRecovered(SOURCE_KEY)}>
                Discard it</button>
            </p>
          </div>
        )}
        <label>Headline
          <input name="headline" required value={fields.headline} onChange={set("headline")} disabled={busy}
                 aria-invalid={problems.headline ? true : undefined} />
          <span className={`client-sub${problems.headline ? " is-over" : ""}`} data-headline-note>
            {problems.headline ?? HEADLINE_NOTE}</span>
        </label>
        <label>Source address
          <input name="source_url" type="url" required placeholder="https://" value={fields.source_url}
                 onChange={set("source_url")} disabled={busy} aria-invalid={problems.source_url ? true : undefined} />
          <span className={`client-sub${problems.source_url ? " is-over" : ""}`} data-source-url-note>
            {problems.source_url ?? SOURCE_URL_NOTE}</span>
        </label>
        <fieldset className="client-when" disabled={busy}>
          <legend>Published</legend>
          <label>Date<input name="date" type="date" required value={fields.date} onChange={set("date")} /></label>
          <label>Time<input name="time" type="time" required value={fields.time} onChange={set("time")} /></label>
          <label>UTC offset
            <select name="offset" required value={fields.offset} onChange={set("offset")}>
              <option value="">Choose…</option>
              {OFFSETS.map((offset) => <option key={offset} value={offset}>UTC{offset}</option>)}
            </select>
          </label>
        </fieldset>
        <label>Source text
          <textarea name="source_text" required rows={12} value={fields.text} onChange={set("text")} disabled={busy} />
          <span className={`client-sub${problems.text ? " is-over" : ""}`}>
            {characters.toLocaleString("en-US")} of {MAX_SOURCE_CHARACTERS.toLocaleString("en-US")} characters</span>
          <span className="client-sub" data-source-size>{SOURCE_SIZE_NOTE}</span>
        </label>
        {notice && <NoticeView notice={notice} />}
        <p className="client-actions">
          <button type="submit" className="button client-save-source" disabled={busy || Object.keys(problems).length > 0}>
            {busy ? "Saving…" : "Save the source"}</button>
        </p>
      </form>
    </>
  );
}
