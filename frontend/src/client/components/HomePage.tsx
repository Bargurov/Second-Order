import { useEffect } from "react";
import { Link } from "../../router";
import { accountOf, useClient } from "../context";
import { href } from "../paths.ts";
import { historyRows } from "../present.ts";
import { useRead } from "../useRead.ts";
import { Entitlements } from "./Entitlements";
import { FirstUse } from "./FirstUse";
import { NoticeView } from "./NoticeView";

/** Your analyses, newest first, with your allowance and any step the server says is still missing. Reading this page
 * uses no credits or allowance. */
export function HomePage() {
  const { account } = useClient();
  const [listed, again] = useRead((api) => api.analyses(), "analyses");
  useEffect(() => { document.title = "Your analyses · Second Order"; }, []);
  return (
    <>
      <header className="client-header">
        <p className="kicker">Research workspace</p>
        <h1 className="client-title">Your analyses</h1>
        <p className="client-lede">Evidence-first analyses of sources you add: what each source establishes, quoted and
          located in its text, kept apart from any interpretation and from what remains unknown.</p>
        <p className="client-actions"><Link className="button" to={href.newSource}>Add a source</Link></p>
      </header>
      <FirstUse />
      <Entitlements />
      <section className="card client-card" aria-labelledby="history-title">
        <h2 id="history-title">History</h2>
        {listed.state === "loading" && <p className="client-status" role="status">Reading your analyses…</p>}
        {listed.state === "notice" && <NoticeView notice={listed.notice} onReadAgain={again} />}
        {listed.state === "ready" && (listed.data.analyses.length === 0 ? (
          <p className="client-empty">No analyses yet. Add a source, choose an Effort, and prepare its analysis.</p>
        ) : (
          <ol className="client-history">
            {historyRows(listed.data.analyses, accountOf(account)).map((row) => (
              <li key={row.analysisId} className="client-history-row" data-analysis={row.analysisId}>
                <Link to={href.analysis(row.analysisId)} className="client-history-title">{row.headline}</Link>
                <p className="client-chips">
                  <span className="client-chip">{row.effort}</span>
                  <span className="client-chip is-state" data-state={row.stateKey}>{row.state}</span>
                  {row.outcome && <span className="client-chip is-outcome" data-outcome={row.outcomeKey}>{row.outcome}</span>}
                  {row.review && <span className="client-chip is-review">{row.review}</span>}
                </p>
                <p className="client-sub">Prepared {row.prepared}{row.credits ? ` · ${row.credits}` : ""}</p>
              </li>
            ))}
          </ol>
        ))}
      </section>
    </>
  );
}
