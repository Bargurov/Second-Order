import { useEffect, useRef, useState } from "react";
import type { Effort, EffortOption, Source } from "../../contracts/user.ts";
import { Link, navigate } from "../../router";
import { accountOf, useClient, zoneOf } from "../context";
import { outcomeOf } from "../controller.ts";
import { href } from "../paths.ts";
import { OUTCOME_LABEL, STATE_LABEL, effortLabel } from "../present.ts";
import type { Notice } from "../refusals.ts";
import { inUtc, inZone } from "../time.ts";
import { useRead } from "../useRead.ts";
import { Entitlements } from "./Entitlements";
import { NoticeView } from "./NoticeView";

/** The sources you added, newest captured first. */
export function SourcesPage() {
  const { account } = useClient();
  const [listed, again] = useRead((api) => api.sources(), "sources");
  useEffect(() => { document.title = "Your sources · Second Order"; }, []);
  const zone = zoneOf(account);
  return (
    <>
      <header className="client-header">
        <p className="kicker">Research workspace</p>
        <h1 className="client-title">Your sources</h1>
        <p className="client-actions"><Link className="button" to={href.newSource}>Add a source</Link></p>
      </header>
      <section className="card client-card" aria-label="Sources">
        {listed.state === "loading" && <p className="client-status" role="status">Reading your sources…</p>}
        {listed.state === "notice" && <NoticeView notice={listed.notice} onReadAgain={again} />}
        {listed.state === "ready" && (listed.data.sources.length === 0
          ? <p className="client-empty">No sources yet.</p>
          : (
            <ol className="client-history">
              {[...listed.data.sources].sort((a, b) => Date.parse(b.captured_at) - Date.parse(a.captured_at)).map((source) => (
                <li key={source.source_id} className="client-history-row" data-source={source.source_id}>
                  <Link to={href.source(source.source_id)} className="client-history-title">{source.headline}</Link>
                  <p className="client-sub">Published {inZone(source.published_at, zone)} · added {inZone(source.captured_at, zone)}
                    {" "}· {source.characters.toLocaleString("en-US")} characters</p>
                </li>
              ))}
            </ol>
          ))}
      </section>
    </>
  );
}

export function SourceFacts({ source, zone }: { source: Source; zone: string }) {
  return (
    <>
      <dl className="ledger client-ledger client-source-facts">
        <div><dt>Address</dt><dd><a href={source.source_url} target="_blank" rel="noreferrer">{source.source_url}</a></dd></div>
        <div><dt>Published</dt><dd>{source.published_at_as_supplied} as supplied<span className="client-sub">
          {inUtc(source.published_at)}</span></dd></div>
        <div><dt>Added</dt><dd>{inZone(source.captured_at, zone)}</dd></div>
      </dl>
      <details className="client-source-text">
        <summary>Source text ({source.characters.toLocaleString("en-US")} characters, as you supplied it)</summary>
        <pre>{source.text}</pre>
      </details>
    </>
  );
}

/** One source: its text, its analyses, and the Effort choice that prepares the next one. */
export function SourcePage({ sourceId }: { sourceId: string }) {
  const { api, account, endSession } = useClient();
  const [detail, again] = useRead((client) => client.source(sourceId), `source:${sourceId}`);
  const [effort, setEffort] = useState<Effort | null>(null);
  const [offered, setOffered] = useState<EffortOption[] | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const acting = useRef(false);
  const zone = zoneOf(account);
  const current = accountOf(account);
  const options = offered ?? current?.efforts ?? [];

  useEffect(() => {
    document.title = `${detail.state === "ready" ? detail.data.source.headline : "Source"} · Second Order`;
  }, [detail]);

  if (detail.state === "loading") return <p className="client-status" role="status">Reading the source…</p>;
  if (detail.state === "notice") {
    return <section className="card client-card"><NoticeView notice={detail.notice} onReadAgain={again} /></section>;
  }
  const { source, analyses } = detail.data;

  const prepare = async () => {
    if (acting.current || effort === null) return;
    acting.current = true;
    setBusy(true);
    setNotice(null);
    // The server resolves the current preparation. An older analysis at this Effort stays in history and must not
    // block a new preparation; the same current preparation is reopened without creating another or sending it.
    const outcome = outcomeOf(await api.prepareAnalysis(sourceId, effort), null, zone);
    acting.current = false;
    setBusy(false);
    if (outcome.kind === "ok") navigate(href.analysis(outcome.data.analysis.analysis_id));
    else if (outcome.kind === "session") endSession(outcome.reason);
    else {
      setNotice(outcome.notice);
      if (outcome.notice.efforts) {  // The server's current options replace the ones shown; nothing is chosen for you.
        setOffered(outcome.notice.efforts);
        setEffort(null);
      }
    }
  };

  return (
    <>
      <header className="client-header">
        <p className="kicker">Source</p>
        <h1 className="client-title">{source.headline}</h1>
      </header>
      <section className="card client-card" aria-label="Source">
        <SourceFacts source={source} zone={zone} />
      </section>
      <section className="card client-card client-effort" aria-labelledby="effort-title">
        <h2 id="effort-title">Prepare an analysis</h2>
        <p className="card-note">Choose an Effort first. Continuing opens the matching saved analysis, or prepares one
          if needed. This uses no credits and sends nothing. A new analysis runs only after you approve its credit
          quote. Earlier analyses stay available below.</p>
        {options.length === 0 ? (
          <p className="client-advisory">The server offers no Effort for analyses right now.
            {current && !current.analysis.available ? ` ${current.analysis.detail}` : ""}</p>
        ) : (
          <fieldset className="client-efforts" disabled={busy}>
            <legend>Effort</legend>
            {options.map((option) => (
              <label key={option.effort} className="client-effort-option">
                <input type="radio" name="effort" value={option.effort} checked={effort === option.effort}
                       onChange={() => { setEffort(option.effort); setNotice(null); }} />
                <span>{option.label}</span>
              </label>
            ))}
          </fieldset>
        )}
        {current && <p className="client-note">{current.effort_note}</p>}
        {notice && <NoticeView notice={notice} />}
        <p className="client-actions">
          <button type="button" className="button client-prepare" disabled={effort === null || busy}
                  onClick={() => void prepare()}>
            {busy ? "Continuing…" : effort ? `Continue with ${effortLabel(effort, current)} Effort`
              : "Choose an Effort to continue"}</button>
        </p>
      </section>
      <section className="card client-card" aria-labelledby="source-analyses-title">
        <h2 id="source-analyses-title">Analyses of this source</h2>
        {analyses.length === 0 ? <p className="client-empty">None yet.</p> : (
          <ul className="client-history">
            {analyses.map((row) => (
              <li key={row.analysis_id} className="client-history-row">
                <Link to={href.analysis(row.analysis_id)} className="client-history-title">
                  {effortLabel(row.effort, current)} Effort</Link>
                <span className="client-chip is-state" data-state={row.state}>{STATE_LABEL[row.state]}</span>
                {row.outcome && <span className="client-chip" data-outcome={row.outcome}>
                  {OUTCOME_LABEL[row.outcome]}</span>}
                <p className="client-sub">Prepared {inZone(row.prepared_at, zone)}</p>
              </li>
            ))}
          </ul>
        )}
        <p className="client-sub">Each saved analysis stays available. Continuing never changes an analysis already
          prepared or run.</p>
      </section>
      <Entitlements compact />
    </>
  );
}
