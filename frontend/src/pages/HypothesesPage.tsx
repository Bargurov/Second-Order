import { useEffect, useState, type CSSProperties } from "react";
import { useLoad } from "../api";
import { fetchJournal, type JournalRow } from "../assessment";
import { AssessmentList } from "../components/AssessmentFlow";
import { FreezeFlow } from "../components/FreezeFlow";
import { OutcomeRetrieval } from "../components/OutcomeRetrieval";
import { ReadinessPanel } from "../components/ReadinessPanel";
import { formatUtc } from "../format";
import { ORIGIN_LABEL, hypothesisHref, providerName, type StoreState } from "../lifecycle";
import { Link } from "../router";
import "../intake.css";
import "../lifecycle.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/** The lifecycle journal of the store's frozen hypotheses, outcome data, and the one deliberate path to a new freeze.
 * Loading the page only reads. */
export function HypothesesPage() {
  const [version, setVersion] = useState(0);
  const [overview, retry] = useLoad(fetchJournal, `overview:${version}`);
  // The last store state read. The freeze flow stays mounted while the overview reloads after an import or a freeze,
  // so its form, choices and outcome are never lost to a refresh of the list.
  const [store, setStore] = useState<StoreState | null>(null);
  // Likewise the last journal rows: the outcome-data card keeps its plan and result while the journal reloads.
  const [rows, setRows] = useState<JournalRow[] | null>(null);
  useEffect(() => {
    if (overview.state === "ready") {
      setStore(overview.data.store);
      setRows(overview.data.hypotheses);
    }
  }, [overview]);
  useEffect(() => {
    document.title = "Hypotheses · Second Order";
  }, []);
  return (
    <article className="hypotheses">
      <header className="hypotheses-header reveal" style={order(0)}>
        <p className="kicker">Hypotheses</p>
        <h1>Freeze a hypothesis before its outcome</h1>
        <p className="lede">
          A frozen hypothesis is stored once, with its baseline, and can never be edited, restamped or frozen again.
          Downloading outcome data, assessing a hypothesis and preparing its Dossier are separate explicit actions; this
          page calls no model, and loading it only reads.
        </p>
      </header>
      <section className="card hypotheses-list reveal" style={order(1)} aria-labelledby="frozen-title">
        <h2 id="frozen-title">Journal</h2>
        {overview.state === "loading" && <p role="status">Loading the store…</p>}
        {overview.state !== "loading" && overview.state !== "ready" && (
          <div role="alert"><p>{overview.message}</p>
            <button type="button" className="button" onClick={retry}>Try again</button></div>
        )}
        {overview.state === "ready" && (
          <>
            <p className="card-note">{overview.data.classification}</p>
            {overview.data.order && <p className="card-note">{overview.data.order}</p>}
            {overview.data.hypotheses.length === 0 ? <p className="freeze-empty">No hypothesis is frozen in this store.</p> : (
              <ul className="frozen-list">
                {overview.data.hypotheses.map((row) => <JournalEntry key={row.hypothesis_id} row={row} />)}
              </ul>
            )}
          </>
        )}
      </section>
      <section className="card hypotheses-outcome reveal" style={order(2)} aria-labelledby="outcome-data-title">
        <h2 id="outcome-data-title">Outcome data</h2>
        <p className="card-note">One approved download of the Board's release package can serve several hypotheses; a
          selection that is already covered needs none. Importing and assessing stay separate steps on each hypothesis's
          page.</p>
        {rows ? <OutcomeRetrieval rows={rows} onChanged={() => setVersion((value) => value + 1)} />
          : <p className="freeze-note">The journal is needed first.</p>}
      </section>
      <section className="card hypotheses-readiness reveal" style={order(3)} aria-labelledby="readiness-title">
        <h2 id="readiness-title">Before a freeze: readiness</h2>
        <p className="card-note">What can be frozen prospectively for a publication date, what is missing, and the next
          explicit action. Freeze readiness, later outcome data and research use are separate questions.</p>
        <ReadinessPanel />
      </section>
      <section className="card hypotheses-new reveal" style={order(4)} aria-labelledby="new-freeze-title">
        <h2 id="new-freeze-title">New freeze</h2>
        {store ? (
          <FreezeFlow store={store} onFrozen={() => setVersion((value) => value + 1)}
                      onStoreChanged={() => setVersion((value) => value + 1)} />
        ) : <p className="freeze-note">The store's state is needed first.</p>}
      </section>
    </article>
  );
}

/** One frozen hypothesis in the journal: its lifecycle state, origin, provider and every recorded assessment. */
function JournalEntry({ row }: { row: JournalRow }) {
  return (
    <li data-hypothesis={row.hypothesis_id} data-state={row.state ?? "none"}>
      <Link to={hypothesisHref(row.hypothesis_id)} className="frozen-headline">{row.headline}</Link>
      <span className="frozen-meta">{row.state_label ?? row.status} · frozen {formatUtc(row.frozen_at)} · {row.usage} ·
        {" "}{ORIGIN_LABEL[row.origin]}{row.provider ? ` · ${providerName(row.provider)}` : ""}
        {row.expected_target && row.state !== "recorded" ? ` · expected target ${row.expected_target}` : ""}</span>
      {row.assessments.length > 0 && <AssessmentList hypothesisId={row.hypothesis_id} rows={row.assessments} />}
    </li>
  );
}
