import { useState } from "react";
import { useLoad } from "../api";
import { DATE, STATUS_LABEL, fetchReadiness, groupRows, type ObservableRow, type Readiness } from "../readiness";

/**
 * Readiness before a freeze: for a publication date (default today in New York), what can be frozen prospectively,
 * what outcome data will be needed later, whether research use is possible, and the next explicit action. Plain
 * language first; the technical provenance is folded below. Checking only reads.
 */
export function ReadinessPanel() {
  const [draft, setDraft] = useState("");
  const [published, setPublished] = useState<string | null>(null);
  const [loaded, retry] = useLoad((signal) => fetchReadiness(published, signal), `readiness:${published ?? "today"}`);
  const invalid = draft !== "" && !DATE.test(draft);
  return (
    <div className="readiness">
      <form className="readiness-date" onSubmit={(event) => {
        event.preventDefault();
        if (!invalid) setPublished(draft || null);
      }}>
        <label>
          <span>Publication date (New York)</span>
          <input type="date" value={draft} aria-invalid={invalid} onChange={(event) => setDraft(event.target.value)} />
        </label>
        <button type="submit" className="button" disabled={invalid}>Check</button>
        <small>Empty means today. Checking only reads: nothing is downloaded, imported, upgraded or frozen.</small>
      </form>
      {loaded.state === "loading" && <p role="status">Reading the store and the kept packages…</p>}
      {loaded.state !== "loading" && loaded.state !== "ready" && (
        <div role="alert"><p>{loaded.message}</p>
          <button type="button" className="button" onClick={retry}>Try again</button></div>
      )}
      {loaded.state === "ready" && <ReadinessResult data={loaded.data} />}
    </div>
  );
}

function ReadinessResult({ data }: { data: Readiness }) {
  const { connected, concepts } = groupRows(data.observables);
  return (
    <div className="readiness-result" data-published={data.published_date}>
      <dl className="readiness-answer">
        <dt>Freeze now</dt><dd data-answer="freeze">{data.answer.freeze_now}</dd>
        <dt>Outcome data</dt><dd data-answer="outcomes">{data.answer.outcomes}</dd>
        <dt>Research use</dt><dd data-answer="research">{data.research.plain}</dd>
      </dl>
      <h3>Next explicit actions</h3>
      <ol className="readiness-actions">
        {data.next_actions.map((item) => (
          <li key={`${item.provider ?? "store"}`} data-status={item.status}><strong>{item.name}.</strong> {item.action}</li>
        ))}
      </ol>
      <h3>Connected observables</h3>
      <p className="freeze-note">A freeze binds every leg to one provider and one baseline, and needs at least two
        distinct observables: {data.providers.map((item) => `${item.name} offers ${item.observables.length}`).join("; ")}.</p>
      <ul className="readiness-rows">
        {connected.map((row) => <ConnectedRow key={row.observable_id} row={row} />)}
      </ul>
      <h3>Registry concepts with no provider</h3>
      <p className="freeze-note">The registry recognises these IDs, but no provider supplies them: none can be frozen for
        measurement. {concepts[0]?.next_action}</p>
      <ul className="readiness-rows readiness-concepts">
        {concepts.map((row) => (
          <li key={row.observable_id} data-observable={row.observable_id} data-status={row.status}>
            <span className="readiness-name">{row.label}<code>{row.observable_id}</code></span>
            <span>{row.plain}</span>
          </li>
        ))}
      </ul>
      <h3>What research use would need (owner decisions)</h3>
      <ul className="freeze-reasons">{data.research.decisions.map((item) => <li key={item}>{item}</li>)}</ul>
      <details className="readiness-provenance">
        <summary>Technical provenance</summary>
        <Provenance data={data} rows={connected} />
      </details>
    </div>
  );
}

function ConnectedRow({ row }: { row: ObservableRow }) {
  return (
    <li data-observable={row.observable_id} data-status={row.status}>
      <span className="readiness-name">{row.label}<code>{row.observable_id}</code></span>
      <span>
        <span className="readiness-status">{STATUS_LABEL[row.status]}</span> {row.plain}
        {!row.freeze.ready && <span className="readiness-next">Next: {row.next_action}</span>}
      </span>
    </li>
  );
}

function Provenance({ data, rows }: { data: Readiness; rows: ObservableRow[] }) {
  const source = data.provenance;
  return (
    <div className="freeze-block readiness-technical">
      <p className="freeze-snapshot">Readiness {data.readiness_version} · checked {source.checked_at} · today (New York)
        {" "}{source.today_new_york} · publication date {data.published_date} · required session {data.required_session}
        {data.required_session_ended ? " (ended)" : " (not ended)"}</p>
      <p className="freeze-snapshot">{source.required_session_rule} Policy {source.freshness_policy}. Rules
        {" "}{source.rules.version} (SHA-256 {source.rules.hash}), at least {source.rules.min_windows} usable reference
        windows. Calendar {source.calendar.calendar} ({source.calendar.library} {source.calendar.library_version},
        exceptions {source.calendar.exceptions_version}).</p>
      <p className="freeze-snapshot">Store: {data.store.exists ? `schema ${data.store.schema}` : "none"}
        {data.store.detail ? ` · ${data.store.detail}` : ""}</p>
      {rows.map((row) => (
        <div key={row.observable_id} className="readiness-source">
          <h4>{row.label} · {row.registry.source}</h4>
          <p className="freeze-note">{row.provider?.connection}</p>
          <ul>
            {(row.retained.snapshots ?? []).map((item) => (
              <li key={item.snapshot_id} className="freeze-snapshot">
                Snapshot {item.snapshot_id} · received {item.retrieved_at}
                {item.verified ? ` · classified ${item.classified_from} to ${item.classified_through}` : ` · ${item.problem}`}
                {item.history_checked ? ` · scorable horizons ${(item.scorable_horizons ?? []).join(", ") || "none"}` : ""}
              </li>
            ))}
            {(row.retained.packages ?? []).map((item) => (
              <li key={item.package_id} className="freeze-snapshot">
                Kept package {item.package_id} · {item.status} · received {item.received_at}
                {item.coverage ? ` · states ${item.coverage.first} to ${item.coverage.last}` : ""}
                {item.imported_as.length ? ` · imported as ${item.imported_as.map((id) => id.slice(0, 12)).join(", ")}`
                  : " · not imported"}
              </li>
            ))}
          </ul>
          {row.freeze.blockers.length > 0 && (
            <ul className="freeze-reasons">{row.freeze.blockers.map((item) => <li key={item}>{item}</li>)}</ul>
          )}
          {row.outcome && <p className="freeze-note">{row.outcome.path}</p>}
        </div>
      ))}
      {source.package_problems.map((item) => (
        <p key={item.retrieval} className="freeze-problem">{item.retrieval}: {item.problem}</p>
      ))}
    </div>
  );
}
