import { useEffect, useRef, useState } from "react";
import type { ImportPreview, ImportState } from "../../contracts/news.ts";
import { Link, navigate } from "../../router";
import { useClient, zoneOf } from "../context";
import { outcomeOf } from "../controller.ts";
import { offerPaste } from "../newsView.ts";
import { href } from "../paths.ts";
import type { Notice } from "../refusals.ts";
import { inUtc, inZone } from "../time.ts";
import { useNewsRead } from "../useRead.ts";
import { NoticeView } from "./NoticeView";

const STATE_TEXT: Record<ImportState, string> = {
  ready: "Ready for you to check", confirming: "Being saved", confirmed: "Saved as your source",
  interrupted: "Stopped before it finished", unreadable: "Not readable as the publication's text",
};

const thousands = (count: number) => count.toLocaleString("en-US");

/** The paste step for this import's publication: its headline and official address only; the time and the text are
 * typed from the official page. */
function pasteFrom(preview: ImportPreview): void {
  offerPaste({ entryId: preview.entry.entry_id, publisher: preview.entry.publisher, title: preview.entry.title,
    link: preview.entry.link, fields: { headline: preview.entry.title, source_url: preview.entry.link, date: "", time: "",
      offset: "", text: "" },
    notes: ["Paste the publication's own text from its official page.",
            "Type the publication's date, time and UTC offset from the official page."] });
  navigate(href.newSource);
}

/** One publication import (GET /api/user/news/imports/{id}, a read): where the text came from, exactly the text that
 * would be saved and what was left out of it. Saving it as the person's source is their explicit confirmation of this
 * text; it analyses nothing. A reply that is not confirmed is read again, never sent again on its own. */
export function ImportPage({ importId }: { importId: string }) {
  const { news, account, endSession } = useClient();
  const zone = zoneOf(account);
  const [read, again] = useNewsRead((api) => api.importPreview(importId), `import:${importId}`);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const sending = useRef(false);
  const preview = read.state === "ready" ? read.data.import : null;
  useEffect(() => {
    document.title = `${preview ? preview.proposed_source.headline : "Publication import"} · Second Order`;
  }, [preview]);

  if (!preview) {
    return (
      <section className="card client-card">
        {read.state === "loading" && <p className="client-status" role="status">Reading the import…</p>}
        {read.state === "notice" && <NoticeView notice={read.notice} onReadAgain={again} />}
        <p className="client-sub"><Link to={href.news}>Back to the news</Link></p>
      </section>
    );
  }

  const proposed = preview.proposed_source, publication = preview.publication;
  const confirm = async () => {
    if (!checked || sending.current) return;
    sending.current = true;
    setBusy(true);
    setNotice(null);
    const reply = await news.confirmImport(preview.import_id, proposed.text_sha256);
    sending.current = false;
    setBusy(false);
    const outcome = outcomeOf(reply, null, zone);
    if (outcome.kind === "ok") return navigate(href.source(outcome.data.source.source_id));
    if (outcome.kind === "session") return endSession(outcome.reason);
    setChecked(false);
    setNotice(outcome.notice.tone === "unconfirmed" ? { ...outcome.notice, facts: [...outcome.notice.facts,
      "Read this import again to see whether your source was saved. Confirming again never saves it twice."] }
      : outcome.notice);
  };

  return (
    <>
      <header className="client-header">
        <p className="kicker">Publication import · {preview.entry.publisher}</p>
        <h1 className="client-title">{proposed.headline}</h1>
        <p className="client-chips"><span className="client-chip is-state" data-import-state={preview.state}>
          {STATE_TEXT[preview.state]}</span></p>
        <p className="client-sub"><Link to={href.news}>Back to the news</Link></p>
      </header>

      <section className="card client-card client-import" aria-labelledby="import-check-title" data-import={preview.state}>
        <h2 id="import-check-title">{preview.state === "ready" ? "Check the text, then save it as your source"
          : "Where this text came from"}</h2>
        <ul className="client-import-statements">
          {preview.statements.map((statement) => <li key={statement}>{statement}</li>)}
        </ul>
        <dl className="ledger client-ledger client-import-facts">
          <div><dt>Official page</dt><dd><a href={publication.url} target="_blank" rel="noreferrer">{publication.url}</a></dd></div>
          <div><dt>Retrieved</dt><dd>{inZone(publication.retrieved_at, zone)}<span className="client-sub">
            {publication.retrieval === "reused" ? "A copy this server kept from an earlier request was used; nothing was requested again."
              : "Requested from the publisher for an import."}</span></dd></div>
          <div><dt>Published</dt><dd>{inUtc(proposed.published_at)}<span className="client-sub">{proposed.published_basis}</span></dd></div>
          <div><dt>Text</dt><dd>{thousands(proposed.characters)} characters in {proposed.paragraphs} paragraphs
            <span className="client-sub">SHA-256 {proposed.text_sha256}</span></dd></div>
          <div><dt>Page as retrieved</dt><dd>{thousands(publication.bytes)} bytes{publication.last_modified
            ? `, last modified ${publication.last_modified} (the publisher's header)` : ""}
            <span className="client-sub">SHA-256 {publication.sha256} · read by {publication.extractor}</span></dd></div>
          <div><dt>Terms</dt><dd><a href={publication.terms_url} target="_blank" rel="noreferrer">{publication.terms_url}</a>
            {preview.entry.attribution && <span className="client-sub">{preview.entry.attribution}</span>}</dd></div>
        </dl>

        {notice && <NoticeView notice={notice} busy={busy} onReadAgain={again} />}
        {preview.state === "ready" && (
          <div className="client-import-confirm">
            <label className="client-approve">
              <input type="checkbox" checked={checked} disabled={busy} onChange={(event) => setChecked(event.target.checked)} />
              <span>I have read this text. Save it as my source exactly as shown: {thousands(proposed.characters)} characters
                from the official page of {preview.entry.publisher}.</span>
            </label>
            <p className="client-actions">
              <button type="button" className="button client-confirm-import" disabled={!checked || busy}
                      onClick={() => void confirm()}>{busy ? "Saving…" : "Save as my source"}</button>
              <button type="button" className="client-link-button" disabled={busy} onClick={() => pasteFrom(preview)}>
                Paste it myself instead</button>
            </p>
            <p className="client-sub">Saving counts as one of today's new sources and analyses nothing. You choose an
              Effort, then ask for a quote, each as its own step.</p>
          </div>
        )}
        {preview.state === "confirmed" && preview.source_id && (
          <p className="client-actions"><Link className="button" to={href.source(preview.source_id)}>Open your
            source</Link></p>
        )}
        {preview.state === "confirming" && (
          <p className="client-note">This import is being saved now.{" "}
            <button type="button" className="client-link-button" onClick={again}>Read again</button></p>
        )}
        {preview.state === "interrupted" && (
          <p className="client-note">An earlier confirmation of this import stopped before it finished, so nothing is
            created again from it. An administrator can check it; you can also paste the publication yourself.{" "}
            <button type="button" className="client-link-button" onClick={() => pasteFrom(preview)}>Paste it as a new
              source</button></p>
        )}
        {preview.state === "unreadable" && (
          <p className="client-note">{preview.problem}{" "}
            <button type="button" className="client-link-button" onClick={() => pasteFrom(preview)}>Paste it as a new
              source</button></p>
        )}
      </section>

      {proposed.text !== null && (
        <section className="client-surface client-evidence client-import-text" aria-labelledby="import-text-title">
          <h2 id="import-text-title">The text {preview.state === "confirmed" ? "saved" : "that would be saved"}</h2>
          <p className="client-label">The publisher's words as read from the official page, in their order</p>
          <pre className="client-marked-text">{proposed.text}</pre>
        </section>
      )}
      {preview.left_out.length > 0 && (
        <details className="card client-card client-import-left-out">
          <summary>Left out of the text ({preview.left_out.length})</summary>
          <ul>
            {preview.left_out.map((row, index) => (
              <li key={index}><span className="client-label">{row.kind.replace(/_/g, " ")}</span>{row.text}</li>
            ))}
          </ul>
        </details>
      )}
      {preview.linked_documents.length > 0 && (
        <section className="card client-card client-import-linked" aria-labelledby="import-linked-title">
          <h2 id="import-linked-title">Documents the page links to</h2>
          <p className="client-sub">Named on the page; none was retrieved or included in the text.</p>
          <ul>
            {preview.linked_documents.map((row) => (
              <li key={row.url}><a href={row.url} target="_blank" rel="noreferrer">{row.title || row.url}</a></li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
