import { useEffect, type CSSProperties } from "react";
import { useLoad } from "../api";
import { formatUtc } from "../format";
import {
  bp, fetchOccasion, rankText,
  type Finding, type MeasureRow, type OccasionView, type Rendered,
} from "../insights";
import { Link } from "../router";
import "../insights.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/** One dated occasion of the latest check: its releases, findings, measured changes and provenance. Reads only. */
export function FindingsOccasionPage({ day }: { day: string }) {
  const [loaded, retry] = useLoad((signal) => fetchOccasion(day, signal), `occasion:${day}`);
  useEffect(() => {
    document.title = `Findings · ${day} · Second Order`;
  }, [day]);
  if (loaded.state === "loading") return <p className="state-panel" role="status">Reading the stored result…</p>;
  if (loaded.state !== "ready") {
    return (
      <section className="state-panel" aria-labelledby="occasion-missing">
        <p className="kicker"><Link to="/findings">Findings</Link></p>
        <h1 id="occasion-missing">{loaded.state === "missing" ? "This date has no checked occasion" : "It could not be shown"}</h1>
        <p className="lede">{loaded.message}</p>
        {loaded.state === "error" && <button type="button" className="button" onClick={retry}>Try again</button>}
      </section>
    );
  }
  const view = loaded.data;
  const result = view.result;
  return (
    <article className="findings findings-occasion">
      <header className="findings-header reveal" style={order(0)}>
        <p className="kicker"><Link to="/findings">Findings</Link> · retrospective single-market pilot</p>
        <h1>Treasury yields around {day}</h1>
        <p className="findings-summary" data-state={view.state}>{result ? result.summary : view.detail}</p>
      </header>
      <Releases view={view} />
      {result && (
        <>
          {result.findings.length > 0 ? (
            <section className="findings-cards reveal" style={order(2)} aria-label="Findings">
              {result.findings.map((finding) => <FindingCard key={finding.check} finding={finding} result={result} />)}
            </section>
          ) : (
            <section className="card reveal" style={order(2)} aria-labelledby="none-title">
              <h2 id="none-title">No finding</h2>
              <p>None of the rule checks met its conditions for this date. The measured changes below are the context;
                nothing has been added to fill the space.</p>
            </section>
          )}
          <Measures result={result} />
          <Context result={result} />
          <OtherChecks result={result} />
        </>
      )}
      {view.provenance && result && <Provenance view={view} result={result} />}
      <section className="findings-limits-band reveal" style={order(7)} aria-labelledby="limits-title">
        <h2 id="limits-title" className="kicker">Limitations</h2>
        <ul>{view.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
      </section>
    </article>
  );
}

function Releases({ view }: { view: OccasionView }) {
  return (
    <section className="card reveal" style={order(1)} aria-labelledby="releases-title">
      <h2 id="releases-title">Releases dated {view.date}</h2>
      <ul className="findings-releases">
        {view.events.map((event) => (
          <li key={event.key} data-event={event.key}>
            <a href={event.link} target="_blank" rel="noreferrer">{event.title}</a>
            <span className="findings-meta">{event.publisher} · {event.family_label}</span>
            <ul>{event.records.map((record) => (
              <li key={`${record.origin}:${record.origin_id}`}>
                <Link to={record.href}>{view.origins[record.origin]}</Link>: date from {record.basis
                  ? view.bases[record.basis] : "no usable date"}{record.as_stated ? ` (as stated: ${record.as_stated})` : ""}
              </li>
            ))}</ul>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Values({ row, which }: { row: MeasureRow; which: "start" | "end" }) {
  const point = row[which];
  return (
    <span>{point.date}: {point.values.map((value, index) => (
      <span key={value.series_id}>{index > 0 ? (value.sign < 0 ? " − " : " + ") : ""}{value.text ?? "no value"}
        {" "}<code>{value.series_id}</code></span>
    ))}</span>
  );
}

function FindingCard({ finding, result }: { finding: Finding; result: Rendered }) {
  const rows = finding.observations.map((key) => result.measures.find((row) => row.key === key))
    .filter((row): row is MeasureRow => !!row);
  // The kicker names a single window; rows name theirs only when a finding compares windows (R4).
  const mixed = new Set(rows.map((row) => row.window)).size > 1;
  return (
    <article className="card finding-card" data-check={finding.check}>
      <p className="kicker">Finding · {finding.rule}{finding.window_label ? ` · ${finding.window_label}` : ""}</p>
      <h2>{finding.title}</h2>
      <h3>Observed</h3>
      <table className="findings-table">
        <thead><tr><th scope="col">Measure</th><th scope="col">From</th><th scope="col">To</th>
          <th scope="col" className="findings-num">Change</th>
          <th scope="col">Rank among eligible earlier windows</th></tr></thead>
        <tbody>{rows.map((row) => (
          <tr key={row.key}><th scope="row">{row.label}{mixed && <><br /><small>{row.window_label}</small></>}</th>
            <td><Values row={row} which="start" /></td><td><Values row={row} which="end" /></td>
            <td className="findings-num">{bp(row.change_bp)}</td><td>{rankText(row)}</td></tr>
        ))}</tbody>
      </table>
      <h3>What this adds</h3>
      <p>{finding.adds}</p>
      <h3>Inference <small>(not observed)</small></h3>
      <p className="finding-inference">{finding.inference}</p>
      <div className="finding-columns">
        <div><h3>Alternatives</h3><ul>{finding.alternatives.map((item) => <li key={item}>{item}</li>)}</ul></div>
        <div><h3>Would strengthen</h3><ul>{finding.strengthen.map((item) => <li key={item}>{item}</li>)}</ul>
          <h3>Would weaken</h3><ul>{finding.weaken.map((item) => <li key={item}>{item}</li>)}</ul></div>
      </div>
      {finding.frequency && (
        <p className="findings-note">The same rule check was met on {finding.frequency.met} of
          {" "}{finding.frequency.evaluable} evaluable comparison sessions ({finding.frequency.sessions} sampled). A
          description of how often the pattern appears, not a probability.</p>
      )}
      <p className="findings-rule"><strong>Rule {finding.rule}:</strong> {finding.rule_text}</p>
    </article>
  );
}

function Measures({ result }: { result: Rendered }) {
  return (
    <section className="card reveal" style={order(3)} aria-labelledby="measures-title">
      <h2 id="measures-title">Measured changes</h2>
      <p className="findings-note">Windows: {Object.entries(result.windows).map(([key, window]) =>
        `${key} ${window.start} → ${window.end} (${window.span} step${window.span === 1 ? "" : "s"})`).join("; ")}.
        {result.event_on_grid === false ? " The event date is not a session, so the first window spans one step." : ""}</p>
      <table className="findings-table findings-measures">
        <thead><tr><th scope="col">Measure</th><th scope="col">Window</th><th scope="col" className="findings-num">Change</th>
          <th scope="col">Rank among eligible earlier windows</th></tr></thead>
        <tbody>{result.measures.map((row) => (
          <tr key={row.key} data-key={row.key}><th scope="row">{row.label}</th><td>{row.window}</td>
            <td className="findings-num">{bp(row.change_bp)}</td><td>{row.problem ?? rankText(row)}</td></tr>
        ))}</tbody>
      </table>
    </section>
  );
}

function Context({ result }: { result: Rendered }) {
  return (
    <section className="card reveal" style={order(4)} aria-labelledby="context-title">
      <h2 id="context-title">Context in the same evidence</h2>
      <p>{result.policy_changes.length > 0
        ? result.policy_changes.map((change) => `H.15 states the discount (primary credit) rate as ${change.to} percent from `
          + `${change.date}, after ${change.from} percent.`).join(" ")
        : "H.15 states no change in the discount (primary credit) rate across these windows."}</p>
      {result.nearby.length > 0 ? (
        <><p>Other retained releases dated inside these windows (the measurement cannot separate them):</p>
          <ul>{result.nearby.map((item) => <li key={item.key}>{item.date}: {item.title}</li>)}</ul></>
      ) : <p>No other retained release is dated inside these windows; unretained news may still be.</p>}
    </section>
  );
}

function OtherChecks({ result }: { result: Rendered }) {
  return (
    <section className="card reveal" style={order(5)} aria-labelledby="checks-title">
      <h2 id="checks-title">Rule checks not met</h2>
      <details>
        <summary>{result.other_checks.length} of {result.other_checks.length + result.findings.length} checks</summary>
        <ul className="findings-checks">{result.other_checks.map((item) => (
          <li key={item.check}>{item.check}: {item.outcome === "not_met" ? "not met" : "not evaluable"}
            {item.detail ? ` (${item.detail})` : ""}</li>
        ))}</ul>
      </details>
    </section>
  );
}

function Provenance({ view, result }: { view: OccasionView; result: Rendered }) {
  const provenance = view.provenance!;
  return (
    <section className="card reveal" style={order(6)} aria-labelledby="provenance-title">
      <h2 id="provenance-title">Provenance</h2>
      <dl className="ledger findings-ledger">
        <div><dt>Computed from</dt><dd><code>{provenance.computed_from.package_id}</code>, received
          {" "}{formatUtc(provenance.computed_from.received_at)}</dd></div>
        <div><dt>Same inputs in</dt><dd>{provenance.attested_by.map((item) => item.package_id).join(", ")}</dd></div>
        <div><dt>Result ID</dt><dd><code>{provenance.result_id}</code></dd></div>
        <div><dt>Inputs SHA-256</dt><dd><code>{provenance.inputs_sha256}</code></dd></div>
      </dl>
      <ul className="findings-series">{Object.entries(result.series).map(([id, series]) => (
        <li key={id}><code>{id}</code>: {series.long} ({series.attributes.UNIT}, frequency code
          {" "}{series.attributes.FREQ})</li>
      ))}</ul>
      <p className="findings-note">One publication and one lineage: the Board republishes the Treasury's curves, and
        FRED republishes them again. Comparisons here are calculations within that source, not corroboration.</p>
    </section>
  );
}
