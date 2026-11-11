import { useEffect, useRef, useState } from "react";
import type { DeeperPreview } from "../../contracts/stories.ts";
import type { Effort } from "../../contracts/user.ts";
import { Link, navigate } from "../../router";
import { accountOf, useClient, zoneOf } from "../context";
import { outcomeOf } from "../controller.ts";
import { href } from "../paths.ts";
import type { Notice } from "../refusals.ts";
import { deeperStages, materialBasis } from "../storiesView.ts";
import { inZone } from "../time.ts";
import { useStoriesRead } from "../useRead.ts";
import { NoticeView } from "./NoticeView";

/** The decision before a deeper analysis: exactly which material it uses and what it leaves out, the source text it
 * becomes, what preparing counts, and the Effort. Preparing saves the user's own source and prepares the analysis; the
 * analysis page then shows the credit quote, and nothing runs until the person approves it there. */
export function DeeperPage({ storyId }: { storyId: string }) {
  const [read, again] = useStoriesRead((api) => api.deeper(storyId), `deeper:${storyId}`);
  useEffect(() => { document.title = "Go deeper · Second Order"; }, []);
  if (read.state === "loading") return <p className="client-status" role="status">Reading what would be used…</p>;
  if (read.state === "notice") {
    return <section className="card client-card"><h1 className="client-title">Go deeper</h1>
      <NoticeView notice={read.notice} onReadAgain={again} /></section>;
  }
  return <DeeperDecision preview={read.data.deeper} onReadAgain={again} />;
}

function DeeperDecision({ preview, onReadAgain }: { preview: DeeperPreview; onReadAgain: () => void }) {
  const { stories, account, endSession, readAccount } = useClient();
  const zone = zoneOf(account);
  const efforts = accountOf(account)?.efforts ?? [];
  const [effort, setEffort] = useState<Effort | null>(efforts[0]?.effort ?? null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const sending = useRef(false);
  useEffect(() => { if (effort === null && efforts.length > 0) setEffort(efforts[0].effort); }, [efforts, effort]);

  const prepare = async () => {
    if (sending.current || effort === null) return;  // One request, even for two presses delivered together.
    sending.current = true;
    setBusy(true);
    setNotice(null);
    const reply = await stories.goDeeper(preview.story_id, preview.material_sha256, effort);
    sending.current = false;
    setBusy(false);
    const outcome = outcomeOf(reply, null, zone);
    if (outcome.kind === "ok") {
      void readAccount();
      return navigate(href.analysis(outcome.data.deeper.analysis.analysis_id));
    }
    if (outcome.kind === "session") return endSession(outcome.reason);
    setNotice(outcome.notice.tone === "unconfirmed" ? { ...outcome.notice, facts: [...outcome.notice.facts,
      "Pressing Prepare again with the same material reuses what was saved; it makes no second source."] }
      : outcome.notice);
  };

  const material = preview.material;
  return (
    <>
      <header className="client-header">
        <p className="client-sub"><Link to={href.story(preview.story_id)}>← The story</Link></p>
        <p className="kicker">Go deeper</p>
        <h1 className="client-title">{preview.title}</h1>
        <p className="client-lede">{preview.statement}</p>
      </header>
      {!preview.available && (
        <section className="card client-card" role="status"><p data-deeper-reason>{preview.reason}</p>
          <p><Link to={href.newSource}>Add a source of your own</Link></p></section>
      )}
      <section className="card client-card" aria-labelledby="material-title">
        <h2 id="material-title">What it uses</h2>
        <p data-material-statement>{material.statement}</p>
        <ol className="news-material">
          {material.reports.map((row) => (
            <li key={row.entry_id} data-entry={row.entry_id}>
              <span className="client-label">{row.publisher}</span>
              <a href={row.link} target="_blank" rel="noreferrer">{row.title}</a>
              <span className="client-sub">{row.published_utc ? `Published ${inZone(row.published_utc, zone)}`
                : "No publication time stated"} · <span data-material-basis>{materialBasis(row)}</span>
                {row.synthetic ? " · SYNTHETIC" : ""}</span>
            </li>
          ))}
        </ol>
        {material.not_used.length > 0 && (
          <>
            <h3 className="news-subhead">Left out</h3>
            <ul className="news-material is-left-out">
              {material.not_used.map((row) => (
                <li key={row.entry_id}><span className="client-label">{row.publisher}</span>{row.title}
                  <span className="client-sub">{row.reason}</span></li>
              ))}
            </ul>
          </>
        )}
        {preview.source && (
          <details className="client-source-text">
            <summary>The exact text your source will hold ({preview.source.characters.toLocaleString("en-US")}
              {" "}characters)</summary>
            <pre data-source-text>{preview.source.text}</pre>
          </details>
        )}
      </section>
      {preview.existing && (
        <section className="card client-card" data-existing>
          <h2>You already went deeper on this material</h2>
          <p>Your source from it is saved. <Link to={href.source(preview.existing.source_id)}>Open your source</Link></p>
          {preview.existing.analyses.length > 0 && (
            <ul>{preview.existing.analyses.map((row) => (
              <li key={row.analysis_id}><Link to={href.analysis(row.analysis_id)}>Your analysis ({row.effort})</Link></li>
            ))}</ul>
          )}
        </section>
      )}
      {preview.available && (
        <section className="card client-card" aria-labelledby="prepare-title">
          <h2 id="prepare-title">Prepare your deeper analysis</h2>
          {accountOf(account) && (
            <ul className="news-deeper-stages" data-deeper-stages>
              {deeperStages(accountOf(account)!).map((row) => (
                <li key={row.stage} data-stage={row.stage} data-ready={row.ready}>{row.text}</li>))}
            </ul>
          )}
          {efforts.length === 0 ? (
            <p data-no-effort>Preparing needs an Effort this server offers, and none is offered now.</p>
          ) : (
            <fieldset className="client-efforts" disabled={busy}>
              <legend>Effort</legend>
              {efforts.map((option) => (
                <label key={option.effort} className="client-effort-option">
                  <input type="radio" name="effort" value={option.effort} checked={effort === option.effort}
                         onChange={() => setEffort(option.effort)} /> {option.label}
                </label>
              ))}
              <p className="client-sub">{accountOf(account)?.effort_note}</p>
            </fieldset>
          )}
          <p className="client-note">Preparing saves this material as your own source (one of today's new sources) and
            prepares its analysis (one of today's prepared analyses). It uses no credits and sends nothing. The next page
            shows the credit quote; the analysis runs only if you approve it there.</p>
          {notice && <NoticeView notice={notice} onReadAgain={onReadAgain} busy={busy} />}
          <p className="client-actions">
            <button type="button" className="button news-prepare-deeper" disabled={busy || effort === null}
                    onClick={() => void prepare()}>{busy ? "Preparing…" : "Prepare my deeper analysis"}</button>
            <Link to={href.story(preview.story_id)}>Not now</Link>
          </p>
        </section>
      )}
    </>
  );
}
