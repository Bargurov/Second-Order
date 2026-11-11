import { useState } from "react";
import { useLoad } from "../api";
import { formatUtc } from "../format";
import {
  dayLabel, fetchRelatedMatch, findRelatedCases, relatedCaseHref, type MatchView, type Overlap, type RelatedMatch,
} from "../relatedCases";
import { Link } from "../router";
import "../related.css";

type Action = { state: "idle" | "running" } | { state: "refused" | "unconfirmed"; message: string };

/**
 * The event overview's Related cases section: the stored match for this version of the event, verified by the server,
 * or the explicit local action that finds it. Nothing here is a prediction or a measured effect.
 */
export function RelatedCases({ kind, id }: { kind: string; id: string }) {
  const [loaded, reload] = useLoad((signal) => fetchRelatedMatch(kind, id, signal), `related:${kind}:${id}`);
  const [action, setAction] = useState<Action>({ state: "idle" });
  const find = async () => {
    setAction({ state: "running" });
    const result = await findRelatedCases(kind, id);
    if (result.state === "done") {
      setAction({ state: "idle" });
      reload();
    } else {
      setAction(result);
    }
  };
  let body;
  if (loaded.state === "loading") body = <p role="status">Reading saved related cases…</p>;
  else if (loaded.state !== "ready") {
    body = <p className="related-problem" role="alert">Related cases could not be read: {loaded.message}</p>;
  } else body = <MatchBody view={loaded.data} action={action} onFind={find} />;
  return (
    <section id="overview-related" className="card event-context-section overview-section related-section"
             aria-labelledby="overview-related-title" data-state={loaded.state === "ready" ? loaded.data.state : loaded.state}>
      <h2 id="overview-related-title">Related historical cases</h2>
      {body}
    </section>
  );
}

function MatchBody({ view, action, onFind }: { view: MatchView; action: Action; onFind: () => void }) {
  const event = view.event;
  return (
    <>
      <p className="related-note">{view.coverage_note} {view.matching_note}</p>
      <dl className="ledger related-inputs">
        <div>
          <dt>Inputs read</dt>
          <dd>{event.inputs.map((input) => `${input.label}${input.present ? "" : " (none recorded)"}`).join("; ")}</dd>
        </div>
        <div>
          <dt>Saved classification</dt>
          <dd>{event.hint ? <>{event.hint.category}{event.hint.event_type ? ` · ${event.hint.event_type}` : ""}.{" "}
            <span className="related-hint-note">{event.hint.note}</span></>
            : "None used: no accepted paid classification of this version. Simulated results are never used."}</dd>
        </div>
      </dl>
      {view.state === "not_checked" && (
        <div className="related-action">
          <p>{view.detail}</p>
          <button type="button" className="button" onClick={onFind} disabled={action.state === "running"}>
            {action.state === "running" ? "Finding related cases…" : "Find related historical cases"}
          </button>
          {(action.state === "refused" || action.state === "unconfirmed") && (
            <p className="related-problem" role="alert">{action.message}</p>
          )}
        </div>
      )}
      {view.state === "problem" && <p className="related-problem" role="alert">{view.detail}</p>}
      {view.state === "checked" && view.match && <Checked view={view} />}
    </>
  );
}

function Checked({ view }: { view: MatchView }) {
  const match = view.match!;
  return (
    <div className="related-result">
      {match.related.length === 0 ? (
        <p className="related-none" data-testid="related-none">
          <strong>No related case.</strong> Neither of the {view.cases_available} historical cases shares this event's
          policy instrument together with its sector or country, as this event's text states them.
        </p>
      ) : (
        <ol className="related-list">
          {match.related.map((row) => <RelatedRow key={row.case_id} row={row} note={view.not_compared_note} />)}
        </ol>
      )}
      {match.overlaps.length > 0 && <Overlaps rows={match.overlaps} />}
      <p className="related-provenance">
        Found {formatUtc(match.computed_at)} by the local check, {match.rules_version}, with
        cases {match.collection_version}; saved once as {match.match_id.slice(0, 12)}. {view.historical_note}
      </p>
    </div>
  );
}

function RelatedRow({ row, note }: { row: RelatedMatch; note: string }) {
  return (
    <li className="related-case" data-case={row.case_id}>
      <p className="related-case-meta">
        <span className="related-topic">{row.topic}</span>
        <span>Announced {dayLabel(row.announced)}</span>
        <span>{row.publisher}</span>
      </p>
      <Link to={relatedCaseHref(row.case_id)} className="related-case-title">{row.title}</Link>
      {row.rests_on_hint && <p className="related-hint-flag" role="note">{row.hint_note}</p>}
      <div className="related-explain">
        <section aria-label="Why it matches">
          <h3>Why it matches</h3>
          <ul>{row.shared.map((item) => <li key={item.dimension + item.value}>{item.text}</li>)}</ul>
        </section>
        <section aria-label="What differs">
          <h3>What differs</h3>
          {row.differs.length === 0
            ? <p className="related-muted">Nothing this event's text names differs from the case.</p>
            : <ul>{row.differs.map((item) => <li key={item.dimension}>{item.text}</li>)}</ul>}
          <p className="related-muted">{row.timing}</p>
        </section>
        <section aria-label="Unknown">
          <h3>Unknown from this event's text</h3>
          {row.unknown.length > 0 && <ul>{row.unknown.map((item) => <li key={item.dimension}>{item.text}</li>)}</ul>}
          <p className="related-muted">{note}</p>
          <ul className="related-points">
            {row.not_compared.map((point) => <li key={point.label}><strong>{point.label}</strong> (the case: {point.case_value})</li>)}
          </ul>
        </section>
      </div>
      <p className="related-why"><span className="related-label">Why read it · interpretation</span> {row.why_read}</p>
    </li>
  );
}

function Overlaps({ rows }: { rows: Overlap[] }) {
  return (
    <div className="related-overlaps">
      <h3>Checked, not related</h3>
      <ul>
        {rows.map((row) => (
          <li key={row.case_id} data-overlap={row.case_id}>
            {row.text} <Link to={relatedCaseHref(row.case_id)}>Read the case anyway</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
